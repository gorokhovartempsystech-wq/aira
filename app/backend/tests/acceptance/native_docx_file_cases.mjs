import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const [root,which]=process.argv.slice(2);
const {createNativeDocxFiles}=await import(pathToFileURL(path.join(root,'src/ara/desktop/client/native-docx-file.mjs')));
const {createNativeDocxSave}=await import(pathToFileURL(path.join(root,'src/ara/desktop/client/native-docx-save.mjs')));
const dir=await fs.mkdtemp(path.join(os.tmpdir(),'aira-native-'));
const file=path.join(dir,'requirements.docx');
const data=text=>{const bytes=Buffer.from(text);return {bytes,sha256:createHash('sha256').update(bytes).digest('hex'),storageRevision:7}};
const original=data('synthetic initial DOCX envelope'),next=data('synthetic confirmed export');
const error=code=>e=>e.code===code;
try{
 await fs.writeFile(file,original.bytes);
 let io=fs;
 if(['write_fault','sync_fault','rename_fault','late_change','uncertain'].includes(which)){
  let opens=0;
  io={...fs,open:async(...args)=>{
   const h=await fs.open(...args);
   if(args[1]==='wx')return new Proxy(h,{get(target,key){
    if(key==='writeFile'&&which==='write_fault')return async()=>{throw Error('disk full')};
    if(key==='sync'&&which==='sync_fault')return async()=>{throw Error('sync failed')};
    if(key==='close'&&which==='late_change')return async()=>{await h.close();await fs.writeFile(file,'external')};
    const v=target[key];return typeof v==='function'?v.bind(target):v;
   }});
   if(args[1]==='r'&&which==='uncertain'){await h.close();throw Error('directory sync unavailable')}
   opens++;return h;
  },rename:async(...args)=>{if(which==='rename_fault')throw Error('permission');return fs.rename(...args)}};
 }
 const files=createNativeDocxFiles({io});
 const selected=await files.selected(file);
 assert.deepEqual(Buffer.from(selected.bytes),original.bytes);
 const write=()=>files.write({binding:selected.binding,exported:next});
 if(which==='roundtrip'){
  const receipt=await write();assert.equal(receipt.storageRevision,7);assert.deepEqual(await fs.readFile(file),next.bytes);
  const another=path.join(dir,'new.docx');await files.write({saveAsPath:another,exported:original});assert.deepEqual(await fs.readFile(another),original.bytes);
 }else if(which==='changed'){
  await fs.writeFile(file,'external');await assert.rejects(write,error('file_changed'));assert.equal(await fs.readFile(file,'utf8'),'external');
 }else if(which==='missing'){
  await fs.unlink(file);await assert.rejects(write,error('file_missing'));await assert.rejects(fs.stat(file));
 }else if(which==='exists'){
  await assert.rejects(files.write({saveAsPath:file,exported:next}),error('file_exists'));assert.deepEqual(await fs.readFile(file),original.bytes);
 }else if(which==='symlink'||which==='hardlink'){
  const alias=path.join(dir,'alias.docx');await fs[which==='symlink'?'symlink':'link'](file,alias);
  await assert.rejects(files.selected(alias),error('unsafe_file'));
  if(which==='symlink'){await fs.unlink(file);await fs.symlink(alias,file);await assert.rejects(write)}
 }else if(which==='invalid'){
  await assert.rejects(files.write({binding:selected.binding,exported:{...next,sha256:'bad'}}),error('invalid_export'));
  await assert.rejects(files.write({binding:{},exported:next}),error('invalid_binding'));
  await assert.rejects(files.write({saveAsPath:'relative.docx',exported:next}),error('invalid_path'));
 }else if(['write_fault','sync_fault','rename_fault'].includes(which)){
  await assert.rejects(write,error('file_io_error'));assert.deepEqual(await fs.readFile(file),original.bytes);
 }else if(which==='late_change'){
  await assert.rejects(write,error('file_changed'));assert.equal(await fs.readFile(file,'utf8'),'external');
 }else if(which==='uncertain'){
  await assert.rejects(write,error('write_uncertain'));assert.deepEqual(await fs.readFile(file),next.bytes);
 }else{
  let exports=0,attempts=0;let chosen=path.join(dir,'created.docx');
  const coordinator=createNativeDocxSave({exporter:{exportDocx:async()=>{exports++;return next}},files:{write:async args=>{
   attempts++;if(which==='retry'&&attempts===1)throw Error('failed');return files.write(args);
  }},pickSavePath:async()=>which==='cancel'?null:chosen});
  if(which==='cancel'){assert.equal(await coordinator.save(),null);assert.equal(exports,0);assert.equal(coordinator.status().saved,null)}
  else if(which==='retry'){
   await assert.rejects(coordinator.save());assert.equal(coordinator.status().canRetry,true);
   const expected=Buffer.from(next.bytes);next.bytes.fill(0);await coordinator.retry();assert.equal(exports,1);
   assert.deepEqual(await fs.readFile(chosen),expected);
  }else if(which==='concurrent'){
   const first=coordinator.save();await assert.rejects(coordinator.save(),error('busy'));await first;assert.equal(exports,1);
  }else if(which==='revision'){
   await coordinator.save();assert.deepEqual(coordinator.status().saved,{sha256:next.sha256,storageRevision:7});
   chosen=path.join(dir,'copy.docx');await coordinator.saveAs();assert.deepEqual(await fs.readFile(chosen),next.bytes);
  }else throw Error('unknown case');
 }
 assert.equal((await fs.readdir(dir)).filter(x=>x.startsWith('.aira-')).length,0);
 console.log('ok '+which);
}finally{await fs.rm(dir,{recursive:true,force:true})}
