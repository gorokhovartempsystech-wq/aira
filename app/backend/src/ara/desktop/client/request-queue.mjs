import {requireValue} from './protocol.mjs';
// One bounded FIFO per connected workspace. Stop uses a separate transport lane.
export function createRequestQueue(){
 let tail=Promise.resolve(),retained=0;
 return Object.freeze({wrap(send){
  requireValue(typeof send==='function');
  return request=>{
   requireValue(retained<128,'busy');requireValue(request!==null&&typeof request==='object');
   const copy={...request};if(copy.body instanceof Uint8Array)copy.body=new Uint8Array(copy.body);
   retained++;const result=tail.then(()=>send(Object.freeze(copy)));
   tail=result.then(()=>undefined,()=>undefined);
   return result.finally(()=>{retained--});
  };
 }});
}
