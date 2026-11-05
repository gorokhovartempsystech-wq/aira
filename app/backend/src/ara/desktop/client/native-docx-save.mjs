import {NativeFileError} from './native-docx-file.mjs';
// One coordinator per document. Picker is supplied by the trusted native shell.
export function createNativeDocxSave({exporter,files,pickSavePath,binding=null}){
 let pending=null,busy=false,phase='idle',saved=null,lastError=null;
 function status(){return {phase,busy,canRetry:!!pending&&!busy,hasFile:binding!==null,
  saved:saved?{...saved}:null,error:lastError}}
 async function dispatch({saveAs=false,retry=false}={}){
  if(busy||(!retry&&pending)|| (retry&&!pending))throw new NativeFileError('busy');
  busy=true;lastError=null;
  try{
   // Choose before exporting, so cancellation does not save the editor internally.
   let chosen=null;
   if(saveAs||binding===null){
    phase='choosing';chosen=await pickSavePath();
    if(chosen===null){phase=pending?'pending':'cancelled';return null}
   }
   if(!pending){phase='exporting';const value=exporter.status?.().canRetry?await exporter.retry():await exporter.exportDocx();pending={...value,bytes:new Uint8Array(value.bytes)}}
   phase='writing';const receipt=await files.write({exported:pending,binding,saveAsPath:chosen});
   binding=receipt.binding;saved={sha256:receipt.sha256,storageRevision:receipt.storageRevision};
   pending=null;phase='saved';return {...saved};
  }catch(e){phase=pending?'pending':'error';lastError=e instanceof NativeFileError?e.code:'export_failed';throw new NativeFileError(lastError)}
  finally{busy=false}
 }
 return Object.freeze({status,save:()=>dispatch(),saveAs:()=>dispatch({saveAs:true}),
  retry:()=>dispatch({retry:true}),retryAs:()=>dispatch({retry:true,saveAs:true})});
}
