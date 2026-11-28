'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]+)<\/script>/)[1].replace(/^boot\(\);\s*bootPermitProgress\(\);\s*$/m, '');
const source = {
  state: 'ID', issuer: 'Canyon County', source_url: 'https://example.gov/permits',
  last_successful_refresh: '2026-11-28T06:00:00Z', latest_date_covered: '2026-11-26',
};
const approval = {
  ...source, key: 'ID|CANYON COUNTY|BP2026-0879', permit_id: 'BP2026-0879',
  record_kind: 'building_permit', stage: 'review_approved_no_issue', received_date: '2026-11-19',
  review_result: 'Approved', review_date: '2026-11-19', issued_flag: null, issue_date: null,
  closed_date: null, source_status: 'Active / In Progress', inspection_status: 'unknown',
  last_observed_at: '2026-11-28T06:00:00Z', changes: [],
};
const issuance = {
  ...approval, key: 'ID|CANYON COUNTY|BP2026-0839', permit_id: 'BP2026-0839',
  stage: 'issued', received_date: '2026-11-02', review_date: '2026-11-02',
  issued_flag: true, issue_date: '2026-11-12',
  changes: [{ field: 'stage', previous_value: 'review_approved_no_issue', new_value: 'issued',
    observed_at: '2026-11-28T06:00:00Z', event_date: '2026-11-12' }],
};
const planning = { ...approval, key: 'PLAN-1', permit_id: 'PLAN-1', record_kind: 'planning', stage: 'planning' };

function runtime(fetch) {
  const elements = new Map();
  let downloaded;
  class PreviewUrl extends URL {
    static createObjectURL(blob) { downloaded = blob; return 'blob:permit-progress-preview'; }
    static revokeObjectURL() {}
  }
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {
        value: '', events: new Map(),
        insertAdjacentHTML(_where, markup) { this.options = markup; },
        addEventListener(event, listener) { this.events.set(event, listener); },
      });
      return elements.get(selector);
    },
    createElement() { return { click() {}, remove() {} }; },
    body: { append() {} },
  };
  const context = vm.createContext({ URL: PreviewUrl, Blob, document, fetch, setTimeout: () => {} });
  vm.runInContext(script, context);
  return { context, control: suffix => document.querySelector('#progress-' + suffix), download: () => downloaded.text() };
}

test('Hayden issue evidence requires the city report flag and appears in the lead CSV', () => {
  const { context } = runtime();
  const permit = {
    jurisdiction: 'Hayden', permit_number: 'PB26-0001', issued_date: '2026-10-22', stage: 'PERMITTED',
    source_name: 'City of Hayden issued building permit report', contractor: 'Example Builder',
    raw: { issue_date_verified: true, contractor_role: 'City-reported contractor' },
  };
  assert.equal(context.evidence(permit), 'issued');
  assert.equal(context.evidence({ ...permit, raw: { issue_date_verified: false } }), 'unverified');
  assert.equal(context.evidence({ ...permit, jurisdiction: 'Kootenai County' }), 'unverified');
  assert.equal(context.evidence({ ...permit, issued_date: '2026-10-32' }), 'unverified');
  assert.match(context.csvText([permit]), /"PB26-0001","2026-10-22","issued","2026-10-22"/);
  assert.equal(context.contractorEvidence(permit), 'Source-labeled: City-reported contractor');
  assert.equal(context.contractorEvidence({ ...permit, contractor: null }), 'Not reported');
});

test('Twin Falls issue evidence and attribution stay with the city issuer', () => {
  const { context } = runtime();
  const permit = {
    jurisdiction: 'Twin Falls', permit_number: 'BP26-FIXTURE', issued_date: '2026-10-29',
    source_name: 'City of Twin Falls monthly issued building permit report', contractor: 'Example Builder',
    raw: { issue_date_verified: true, contractor_role: 'City-reported contractor' },
  };
  assert.equal(context.evidence(permit), 'issued');
  assert.match(context.csvText([permit]), /"BP26-FIXTURE","2026-10-29","issued","2026-10-29"/);
  assert.equal(context.contractorEvidence(permit), 'Source-labeled: City-reported contractor');
  assert.equal(context.evidence({ ...permit, raw: {} }), 'unverified');
  assert.equal(context.evidence({ ...permit, jurisdiction: 'Twin Falls County' }), 'unverified');
});

test('building stage filter and CSV distinguish approval and issuance', async () => {
  const { context, control, download } = runtime(async () => ({
    ok: true, json: async () => ({ sources: [source], permits: [approval, issuance, planning] }),
  }));
  await context.bootPermitProgress();
  assert.match(control('building-rows').innerHTML, /BP2026-0879[\s\S]+Review approved · issuance unverified[\s\S]+BP2026-0839[\s\S]+Issuance"><div>Yes[\s\S]+2026-11-12/);
  assert.doesNotMatch(control('building-rows').innerHTML, /PLAN-1/);
  assert.match(control('sources').innerHTML, /Last successful refresh[\s\S]+Latest date covered[\s\S]+2026-11-26/);

  control('stage').value = 'review_approved_no_issue';
  control('stage').events.get('change')();
  assert.match(control('building-rows').innerHTML, /Inspection"><div>Unknown/);
  assert.doesNotMatch(control('building-rows').innerHTML, /BP2026-0839/);
  control('export').events.get('click')();
  let csv = await download();
  assert.match(csv, /"BP2026-0879","building_permit","review_approved_no_issue","2026-11-19","Approved","2026-11-19","",""/);
  assert.doesNotMatch(csv, /BP2026-0839|PLAN-1/);

  control('stage').value = 'issued';
  control('stage').events.get('change')();
  control('export').events.get('click')();
  csv = await download();
  assert.match(csv, /"BP2026-0839","building_permit","issued","2026-11-02","Approved","2026-11-02","true","2026-11-12"/);
  assert.match(csv, /https:\/\/example.gov\/permits/);
  assert.match(control('building-rows').innerHTML, /Official event date 2026-11-12 · Observed /);

  control('planning-kind').checked = true;
  control('planning-kind').events.get('change')();
  assert.equal(control('building').hidden, true);
  assert.match(control('planning-rows').innerHTML, /PLAN-1/);
  assert.doesNotMatch(control('planning-rows').innerHTML, /Issuance|Inspection|BP2026/);
  control('export').events.get('click')();
  assert.doesNotMatch(await download(), /BP2026/);
});

test('permit progress pages rows but exports all issuer and stage matches', async () => {
  const rows = Array.from({ length: 201 }, (_, index) => ({ ...issuance, permit_id: `P-${index}` }));
  rows.push({ ...approval, issuer: 'Nampa', permit_id: 'N-1' });
  const { context, control, download } = runtime(async () => ({ ok: true, json: async () => ({ sources: [source], permits: rows }) }));
  await context.bootPermitProgress();
  control('issuer').value = JSON.stringify(['ID', 'Canyon County']);
  control('issuer').events.get('change')();
  assert.match(control('page').textContent, /Page 1 of 3/);
  assert.equal(control('building-rows').innerHTML.match(/<tr>/g).length, 100);
  control('next').events.get('click')();
  assert.match(control('page').textContent, /Page 2 of 3/);
  control('export').events.get('click')();
  const csv = await download();
  assert.equal(csv.trim().split('\r\n').length, 202);
  assert.doesNotMatch(csv, /N-1/);
});

test('case-insensitive ID search filters the view and CSV and clearing restores matches', async () => {
  const { context, control, download } = runtime(async () => ({
    ok: true, json: async () => ({ sources: [source], permits: [approval, issuance] }),
  }));
  await context.bootPermitProgress();
  control('search').value = ' bp2026-083 ';
  control('search').events.get('input')();
  assert.match(control('building-rows').innerHTML, /BP2026-0839/);
  assert.doesNotMatch(control('building-rows').innerHTML, /BP2026-0879/);
  control('export').events.get('click')();
  const csv = await download();
  assert.match(csv, /BP2026-0839/);
  assert.doesNotMatch(csv, /BP2026-0879/);

  control('search').value = '';
  control('search').events.get('input')();
  assert.match(control('building-rows').innerHTML, /BP2026-0879[\s\S]+BP2026-0839/);
});

test('escaped source content, safe URLs and CSV formula text', () => {
  const { context } = runtime();
  const suspect = { ...approval, permit_id: '<img src=x>', source_status: '=SUM(1,2)', source_url: 'javascript:alert(1)' };
  const row = context.progressRow(suspect);
  assert.match(row, /&lt;img src=x&gt;/);
  assert.doesNotMatch(row, /<img|javascript:/);
  const csv = context.permitProgressCsv([suspect], []);
  assert.match(csv, /"'=SUM\(1,2\)"/);
  assert.doesNotMatch(csv, /javascript:/);
});

test('freshness is from the exact issuer and source stream', () => {
  const { context } = runtime();
  const common = { ...source, issuer: 'Boise' };
  const reports = [
    { ...common, source_name: 'Boise planning', latest_date_covered: '2026-11-23' },
    { ...common, source_name: 'Boise issued', latest_date_covered: '2026-11-26' },
  ];
  const permit = { ...issuance, issuer: 'Boise', source_name: 'Boise issued', source_url: 'https://example.gov/boise/permit/1' };
  const csv = context.permitProgressCsv([permit], reports);
  assert.match(csv, /"Boise issued","https:\/\/example.gov\/boise\/permit\/1"/);
  assert.match(csv, /2026-11-26/);
  assert.doesNotMatch(csv, /2026-11-23/);
});
