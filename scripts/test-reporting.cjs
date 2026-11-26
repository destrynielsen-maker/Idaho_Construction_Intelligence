const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const {execFileSync}=require('node:child_process');
const BASE='11e21dbd7c14a20db232389b47dcbcdf6e8bf33e';
const before=process.argv[2];
const old=before?fs.readFileSync(before,'utf8'):execFileSync('git',['show',BASE+':public/index.html'],{cwd:root,encoding:'utf8'});
const updated=fs.readFileSync(path.join(root,'public/index.html'),'utf8');
const permits=JSON.parse(fs.readFileSync(path.join(root,'public/data/permits.json'),'utf8'));
const src=JSON.parse(fs.readFileSync(path.join(root,'public/data/sources.json'),'utf8'));
function runner(html){
 class Elem {constructor(id){this.value=id==='days'?'30':id==='minScore'?'30':'';this.events={};this.textContent='';this.innerHTML='';}addEventListener(e,f){this.events[e]=f}insertAdjacentHTML(){}}
 const elements=new Map();
 const e=i=>{if(!elements.has(i))elements.set(i,new Elem(i));return elements.get(i)};
 const D=Date;class FixedDate extends D{constructor(...args){super(...(args.length?args:['2026-11-26T18:59:23Z']))}}
 const ctx=vm.createContext({document:{querySelector:s=>e(s.replace('#','')),querySelectorAll:()=>[]},Date:FixedDate,Intl,fetch:u=>Promise.resolve({json:()=>Promise.resolve(u.startsWith('data/permits')?permits:src)})});
 vm.runInContext(html.split('<script>')[1].split('</script>')[0].replace(/boot\(\);\s*$/,'globalThis.bootPromise=boot();'),ctx);
 return {ctx,e,done:ctx.bootPromise};
}
(async()=>{
 const a=runner(old),b=runner(updated);await Promise.all([a.done,b.done]);
 const count=x=>Number(x.e('count').textContent.match(/^[\d,]+/)[0].replaceAll(',',''));
 assert.equal(count(a),49);assert.equal(count(b),49);
 const def=count(b);
 for(const x of [a,b]){x.e('days').value='0';x.e('minScore').value='0';vm.runInContext('render()',x.ctx);}
 assert.equal(count(a),1186);assert.equal(count(b),1186);
 assert.equal(vm.runInContext("csvText(matchingRows).trimEnd().split('\\r\\n').length",b.ctx),1187);
 assert.match(b.e('count').textContent,/showing 1,000/);
 assert.match(b.e('sourceCards').innerHTML,/No successful observation in this run/);
 b.e('evidence').value='issued';vm.runInContext('render()',b.ctx);assert.equal(count(b),653);
 b.e('evidence').value='application received';vm.runInContext('render()',b.ctx);assert.equal(count(b),208);
 b.e('evidence').value='unverified';b.e('jurisdiction').value='Eagle';vm.runInContext('render()',b.ctx);assert.equal(count(b),242);
 assert.equal(vm.runInContext("csvCell('=HYPERLINK(1)')",b.ctx),"\"'=HYPERLINK(1)\"");
 console.log(JSON.stringify({default_matches_before_and_after:def,all_matches:1186,export_rows:1186,display_cap_disclosed:1000,issued:653,application:208,eagle_unverified_visible:242}));
})().catch(e=>{console.error(e);process.exitCode=1});
