// Trusted Node desktop host only. Never import into a browser/HTTP route.
import * as fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
const LIMIT=32*1024*1024;
export class NativeFileError extends Error {
 constructor(code){super(code);this.name='NativeFileError';this.code=code}
}
const fail=code=>{throw new NativeFileError(code)};
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const fingerprint=(s,sha256)=>({dev:String(s.dev),ino:String(s.ino),size:String(s.size),mtime:String(s.mtimeNs),ctime:String(s.ctimeNs),sha256});
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function payload(value){
 if(!(value?.bytes instanceof Uint8Array)||!value.bytes.length||value.bytes.length>LIMIT
  ||!Number.isSafeInteger(value.storageRevision)||value.storageRevision<1)fail('invalid_export');
 const bytes=Buffer.from(value.bytes);
 if(digest(bytes)!==value.sha256)fail('invalid_export');
 return {...value,bytes};
}
export function createNativeDocxFiles({io=fs}={}){
 // Injectable filesystem exists for fault acceptance, never for renderer input.
 const bindings=new WeakMap();let busy=false;
 async function destination(raw){
  if(typeof raw!=='string'||!path.isAbsolute(raw)||raw.includes('\0')||path.extname(raw).toLowerCase()!=='.docx')fail('invalid_path');
  return path.join(await io.realpath(path.dirname(raw)),path.basename(raw));
 }
 async function read(file){
  const initial=await io.lstat(file,{bigint:true});
  if(!initial.isFile()||initial.isSymbolicLink()||initial.nlink!==1n||initial.size>BigInt(LIMIT))fail('unsafe_file');
  const handle=await io.open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0));
  try{
   const before=await handle.stat({bigint:true});
   if(before.dev!==initial.dev||before.ino!==initial.ino||!before.isFile()||before.nlink!==1n)fail('file_changed');
   // Bounded read even if another application grows the file after stat.
   if(before.size>BigInt(LIMIT))fail('unsafe_file');
   const bytes=Buffer.alloc(Number(before.size)+1);let used=0;
   while(used<bytes.length){const r=await handle.read(bytes,used,bytes.length-used,used);if(!r.bytesRead)break;used+=r.bytesRead}
   const after=await handle.stat({bigint:true});const sha=digest(bytes.subarray(0,used));
   if(used!==Number(before.size)||!equal(fingerprint(before,sha),fingerprint(after,sha)))fail('file_changed');
   const last=await io.lstat(file,{bigint:true});
   if(!equal(fingerprint(after,sha),fingerprint(last,sha)))fail('file_changed');
   return {bytes:new Uint8Array(bytes.subarray(0,used)),stamp:fingerprint(after,sha),mode:Number(after.mode)&0o777};
  }finally{await handle.close()}
 }
 function bind(file,stamp){const token=Object.freeze({});bindings.set(token,{file,stamp});return token}
 async function selected(raw){
  try{const file=await destination(raw);const value=await read(file);return {bytes:value.bytes,binding:bind(file,value.stamp)}}
  catch(e){throw safe(e)}
 }
 function safe(e){return e instanceof NativeFileError?e:new NativeFileError(e?.code==='ENOENT'?'file_missing':'file_io_error')}
 async function write({exported,binding=null,saveAsPath=null}){
  if(busy)fail('busy');busy=true;let temp=null,handle=null,published=false;
  try{
   const value=payload(exported);let file,expected=null,mode=0o600;
   if(saveAsPath!==null){file=await destination(saveAsPath)}
   else{const known=bindings.get(binding);if(!known)fail('invalid_binding');file=known.file;expected=known.stamp;
    const current=await read(file);if(!equal(current.stamp,expected))fail('file_changed');mode=current.mode;}
   temp=path.join(path.dirname(file),'.aira-'+randomUUID()+'.tmp');
   handle=await io.open(temp,'wx',mode);await handle.writeFile(value.bytes);await handle.chmod(mode);await handle.sync();await handle.close();handle=null;
   if(expected){
    const current=await read(file);if(!equal(current.stamp,expected))fail('file_changed');
    await io.rename(temp,file);temp=null;published=true;
   }else{
    // Atomic no-replace publication, including a file created during the save.
    try{await io.link(temp,file)}catch(e){if(e.code==='EEXIST')fail('file_exists');throw e}
    published=true;await io.unlink(temp);temp=null;
   }
   // POSIX directory durability. Windows lacks a portable directory fsync API.
   if(process.platform!=='win32'){const directory=await io.open(path.dirname(file),'r');try{await directory.sync()}finally{await directory.close()}}
   const confirmed=await read(file);
   if(confirmed.stamp.sha256!==value.sha256)fail('file_changed');
   return {binding:bind(file,confirmed.stamp),sha256:value.sha256,storageRevision:value.storageRevision};
  }catch(e){if(published)throw new NativeFileError('write_uncertain');throw safe(e)}
  finally{if(handle)await handle.close().catch(()=>{});if(temp)await io.unlink(temp).catch(()=>{});busy=false}
 }
 return Object.freeze({selected,write});
}
