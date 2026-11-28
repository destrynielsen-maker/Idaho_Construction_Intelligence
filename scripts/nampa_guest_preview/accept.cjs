'use strict';
const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
const [oct,nov]=process.argv.slice(2).map(p=>JSON.parse(readFileSync(p,'utf8')));
assert.equal(oct.count,8,'historical residential new scope drift');
const o=new Map(oct.rows.map(x=>[x.id,x]));
assert.equal(o.get('RES-18809-2026')?.issued,'2026-10-19');
assert.equal(o.get('RES-18809-2026')?.contractor,'Hayden Homes Idaho LLC');
assert.equal(o.get('RES-19020-2026')?.issued,'2026-10-19');
assert.equal(o.get('RES-19020-2026')?.contractor,'KB Home Idaho LLC');
assert(!o.has('RES-19080-2026'),'fire-restoration record was not excluded');
const expected={
 'RES-19105-2026':['2026-11-23','Richmond American Homes of Idaho INC'],
 'RES-19090-2026':['2026-11-23',null],
 'RES-18986-2026':['2026-11-24','Hayden Homes Idaho LLC'],
 'RES-18985-2026':['2026-11-24','Hayden Homes Idaho LLC'],
 'RES-19111-2026':['2026-11-23','Hubble Homes LLC'],
 'RES-19089-2026':['2026-11-24','Richmond American Homes of Idaho INC'],
 'RES-19147-2026':['2026-11-24','Richmond American Homes of Idaho INC'],
};
assert.equal(nov.count,7,'November query changed; inspect before any release');
assert.deepEqual(Object.fromEntries(nov.rows.map(r=>[r.id,[r.issued,r.contractor]])),expected);
console.log(JSON.stringify({october:oct.count,november:nov.count,contractorCompanies:nov.rows.filter(r=>r.contractor).length,latest:'2026-11-24',writes:0}));
