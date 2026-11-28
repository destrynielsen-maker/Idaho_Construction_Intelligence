'use strict';
// Read-only preview. No private endpoints, credentials, export uploads, or tracker writes.
const { chromium } = require('playwright');
const HOST = 'https://nampaid-energovpub.tylerhost.net';
const SEARCH = HOST + '/Apps/SelfService#/search';
const TYPE = 'Residential (New Single Family Dwelling, Townhouse, and/or Duplex)';
const ID = /^RES-\d+-20\d{2}$/;
function iso(s) {
  const m=/^(\d{2})\/(\d{2})\/(20\d{2})$/.exec(s);
  if (!m) throw Error('not an explicit issue date');
  const x=m[3]+'-'+m[1]+'-'+m[2], d=new Date(x+'T00:00:00Z');
  if (isNaN(d.valueOf())||d.toISOString().slice(0,10)!==x) throw Error('invalid date');
  return x;
}
function windowOf(a,b) {
  const lo=iso(a),hi=iso(b), span=(Date.parse(hi)-Date.parse(lo))/86400000;
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Boise',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  if(span<0||span>6||hi>today) throw Error('only a bounded past or current municipal week is allowed');
  return {lo,hi};
}
function validate(rows, count, {lo,hi}) {
  if(!Number.isInteger(count)||count<1||count>25||rows.length!==count) throw Error('partial, empty or oversized search result: review manually');
  const seen=new Set();
  for(const r of rows) {
    const u=new URL(r.url);
    if(!ID.test(r.id)||seen.has(r.id)||u.origin!==HOST||!/^\/apps\/selfservice(?:\/NampaIDProd)?\/?$/i.test(u.pathname)||
       !/^#\/permit\/[0-9a-f-]{36}$/i.test(u.hash)||u.search||
       r.type!==TYPE||!['Issued','Finaled','Finalized'].includes(r.status)||
       iso(r.issued)<lo||iso(r.issued)>hi||!r.address) throw Error('identity, status, or issue-date evidence failed');
    seen.add(r.id);
  }
  return rows;
}
function mergeDetail(row, detail) {
  if(detail.id!==row.id||iso(detail.issued)!==iso(row.issued)||!/^\s*NEW\s+(?:SFD|SINGLE[- ]FAMILY|TOWN(?:HOUSE|HOME)|DUPLEX)\b/i.test(detail.scope)||
      /\b(?:restor(?:e|ation)|fire damage|remodel|repair)\b/i.test(detail.scope)) throw Error('detail identity, date or new-build scope not proved');
  const distinct=[...new Set(detail.contractors.map(c=>c.trim()).filter(Boolean))];
  return {...row, issued:iso(row.issued),description:detail.scope,contractor:distinct.length===1?distinct[0]:null};
}
async function guard(page) {
  const url=new URL(page.url());
  if(url.origin!==HOST)throw Error('unexpected navigation');
  const title=await page.title();
  if(/access denied|human verification|just a moment|captcha/i.test(title))throw Error('portal access and verification gate');
}
async function run(from,to) {
  const period=windowOf(from,to);
  const browser=await chromium.launch({headless:true,...(process.env.NAMPA_USE_SYSTEM_CHROME==='1'?{channel:'chrome'}:{})});
  try {
    const page=await browser.newPage();
    page.setDefaultTimeout(10000);
    let restricted=false;
    page.on('response',r=>{ const u=new URL(r.url()); if(u.origin===HOST&&[401,403,429].includes(r.status())&&['document','xhr','fetch'].includes(r.request().resourceType()))restricted=true; });
    // The user-facing search path; only the public form is submitted.
    await page.goto(SEARCH,{waitUntil:'domcontentloaded'});
    await guard(page);
    const mode=page.getByRole('combobox',{name:'Search',exact:true});
    await mode.locator('option:checked').filter({hasText:/^All$/}).waitFor({state:'attached'});
    const dateFrom=page.locator('#IssueDateFrom');
    const advanced=page.getByRole('button',{name:/Advanced/});
    for(let attempt=0;attempt<2;attempt++) {
      if(restricted)throw Error('portal access restricted');
      await guard(page);
      await mode.selectOption({label:'Permit'});
      await mode.locator('option:checked').filter({hasText:/^Permit$/}).waitFor({state:'attached'});
      if(!await dateFrom.isVisible())await advanced.click();
      // The tenant can reset the initial option while the first view is loading.
      if(await dateFrom.waitFor({state:'visible',timeout:3500}).then(()=>true,()=>false))break;
    }
    await dateFrom.waitFor({state:'visible'});
    await page.getByRole('combobox',{name:'Permit Type',exact:true}).selectOption({label:TYPE});
    for(const [k,v] of [['IssueDateFrom',from],['IssueDateTo',to]]) {
      const field=page.locator('#'+k);
      await field.fill(v); await field.press('Tab');
      if(await field.inputValue()!==v || await field.getAttribute('aria-invalid')==='true')throw Error('date entry was not accepted');
    }
    await page.getByRole('button',{name:/Search$/}).click();
    const counter=page.getByText(/^Found \d+ results?$/).first();
    await counter.waitFor({state:'visible'});
    const count=Number((await counter.innerText()).match(/\d+/)[0]);
    if(restricted||count>25||count<1)throw Error('restricted, empty or unbounded search');
    if(count>10)await page.getByRole('combobox',{name:'Page size selection'}).selectOption({label:'25'});
    const expected=new RegExp('^1\\s*-\\s*'+count+' of '+count+'$');
    await page.getByText(expected).waitFor({state:'visible'});
    const rows=await page.getByRole('link',{name:ID}).evaluateAll(anchors=>anchors.map(a=>{
      let p=a.parentElement;
      for(let depth=0; p&&depth<8; depth++,p=p.parentElement) {
        const text=p.innerText;
        if(!text.includes('Issued Date')||!text.includes('Permit Number')||!text.includes('Address'))continue;
        if([...p.querySelectorAll('a[href*="#/permit/"]')].filter(x=>/^RES-\d+-20\d{2}$/.test(x.textContent.trim())).length!==1)break;
        const value=(label)=>{const s=text.split(/\n/).map(s=>s.trim()).find(s=>s.startsWith(label+' ')); return s?s.slice(label.length).trim():''; };
        return {id:a.textContent.trim(),url:a.href,issued:value('Issued Date'),status:value('Status'),type:value('Type'),address:value('Address')};
      }
      return {id:a.textContent.trim(),url:a.href};
    }));
    validate(rows,count,period);
    const out=[];
    for(const r of rows) {
      await page.goto(r.url,{waitUntil:'domcontentloaded'}); await guard(page);
      await page.getByRole('tab',{name:'Contacts',exact:true}).waitFor();
      await page.getByRole('heading',{name:'Permit Number: '+r.id,exact:true}).waitFor();
      await page.getByText('Description:',{exact:true}).waitFor();
      const summary=await page.evaluate(()=>{
        const visible=[...document.querySelectorAll('body *')].filter(e=>e.childElementCount===0&&e.getBoundingClientRect().height);
        const value=(label)=>{
          const tags=visible.filter(e=>e.textContent.trim()===label);
          for(const tag of tags) {
            let n=tag; for(let i=0;i<3&&n;i++,n=n.parentElement) {
              const s=n.innerText.split(/\n/).map(x=>x.trim()).filter(Boolean), at=s.indexOf(label);
              if(at>=0&&s[at+1]&&s[at+1]!==label)return s[at+1];
            }
          } return '';
        };
        return {scope:value('Description:'),issued:value('Issue Date:'),id:visible.map(e=>e.textContent.trim()).find(t=>/^RES-\d+-20\d{2}$/.test(t))||''};
      });
      await page.getByRole('tab',{name:'Contacts',exact:true}).click();
      await page.getByRole('columnheader',{name:'Company',exact:true}).waitFor();
      const contractors=await page.getByRole('row',{name:/Type Registered Building Contractor Company/i}).evaluateAll(rs=>rs.map(r=>r.querySelectorAll('td')[1]?.innerText||''));
      if(restricted)throw Error('portal access restricted');
      out.push(mergeDetail(r,{...summary,contractors}));
    }
    return {scope:TYPE,period,count,rows:out};
  } finally {await browser.close();}
}
module.exports={iso,windowOf,validate,mergeDetail,TYPE};
if(require.main===module)run(process.argv[2],process.argv[3]).then(x=>console.log(JSON.stringify({scope:x.scope,period:x.period,count:x.count,rows:process.argv.includes('--full')?x.rows:x.rows.map(r=>({id:r.id,issued:r.issued,contractor:r.contractor}))},null,2))).catch(e=>{console.error(e.message);process.exitCode=1;});
