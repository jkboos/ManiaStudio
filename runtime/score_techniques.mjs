import {analyzeTechniques} from './technique_analyzer.mjs';
let input='';for await (const chunk of process.stdin) input+=chunk;
const requests=JSON.parse(input);
const result=requests.map(r=>{
  try {const a=analyzeTechniques(r.osu_text);return {candidate:r.candidate,status:'ok',raw:a.raw,primary:a.primary};}
  catch(error) {return {candidate:r.candidate,status:'error',error:String(error)};}
});
process.stdout.write(JSON.stringify(result));
