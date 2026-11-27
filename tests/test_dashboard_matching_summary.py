import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardSummaryTests(unittest.TestCase):
    def test_dashboard_actual_javascript(self):
        node = shutil.which("node")
        if not node:
            if __import__("os").environ.get("GITHUB_ACTIONS") == "true":
                self.fail("Hosted dashboard test requires Node")
            self.skipTest("Node unavailable")
        html = (ROOT / "public/index.html").read_text()
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        # Run actual browser-side helpers, replacing only the network boot invocation.
        script = script[:script.index("boot().catch(")]
        harness = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
generatedAt='2026-11-27T05:09:27Z';
const sample=(key,source_name,issued_date,extra={})=>({key,source_name,issued_date,score:40,classification:'SINGLE_FAMILY',jurisdiction:'Example',valuation:100,...extra});
const issue='Meridian permit report';
const fixtures=[
sample('1',issue,'2026-11-26'),
sample('2','Canyon County DSD Building Permit Tracker','2026-11-25'),
sample('3','Boise Development Tracker','2026-11-24'),
sample('4','Eagle iWorQ Permit Portal','2026-11-23'),
sample('5',issue,'2026-10-28'),
sample('6',issue,'2026-10-27'),
sample('7',issue,'2026-11-27'),
sample('8',issue,'2026-11-99'),
sample('9',issue,'', {valuation:null}),
sample('10',issue,'2026-11-26',{score:10}),
];
assert.equal(mountainToday(new Date('2026-11-27T05:09:27Z')),'2026-11-26');
assert.equal(dateCutoff(30,'2026-11-26'),'2026-10-28');
const matching=filterPermitRows(fixtures,{days:30,today:'2026-11-26',score:30});
assert.deepEqual(matching.map(p=>p.key),['1','2','3','4','5']);
assert.deepEqual(filterPermitRows(fixtures,{days:30,today:'2026-11-26',score:30,dateKind:'issued'}).map(p=>p.key),['1','5']);
assert.equal(filterPermitRows(fixtures).length,10);
assert.equal(filterPermitRows(fixtures,{jur:'missing'}).length,0);
const s=summarizeMatching(matching);
assert.deepEqual([s.total,s.issuedTotal,s.applicationTotal,s.planningTotal,s.unverifiedTotal,s.valuation],[5,2,1,1,1,500]);
assert.equal(summarizeMatching([]).valuationCount,0);
const nodes=new Map();
global.document={querySelector(id){if(!nodes.has(id))nodes.set(id,{textContent:''});return nodes.get(id)}};
permits=fixtures;renderMatchingSummary(matching,30,30);
assert.equal(nodes.get('#total').textContent,'5');
assert.equal(nodes.get('#allPublished').textContent,'10');
renderMatchingSummary([],30,30);
assert.equal(nodes.get('#total').textContent,'0');
assert.equal(nodes.get('#valuation').textContent,'—');
// Exact checked-in snapshot: no policy changes, every published identity
// remains available under the all-date / any-score view.
const payload=JSON.parse(fs.readFileSync('public/data/permits.json','utf8'));
permits=payload.permits;generatedAt=payload.generated_at;
const all=filterPermitRows(permits);
assert.equal(all.length,permits.length);
assert.equal(new Set(all.map(p=>p.key)).size,all.length);
const stats=summarizeMatching(all);
assert.equal(stats.total,stats.issuedTotal+stats.applicationTotal+stats.planningTotal+stats.unverifiedTotal);
const recent=filterPermitRows(permits,{days:30,today:'2026-11-26',score:30});
renderMatchingSummary(recent,30,30);
assert.equal(nodes.get('#total').textContent,recent.length.toLocaleString('en-US'));
assert.equal(csvText(recent).split('\r\n').length,recent.length+2);
console.log(JSON.stringify({published:all.length,all:stats,recent:summarizeMatching(recent)}));
"""
        result = subprocess.run([node, "-"], input=script + "\n" + harness, text=True, capture_output=True, cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
