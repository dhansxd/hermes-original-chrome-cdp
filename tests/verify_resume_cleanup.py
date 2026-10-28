"""Read-only target inventory; no auto-attach, page inspection or mutation."""
import json,sys,hashlib,difflib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import plugin
from vault_adapter import Wire
p=plugin.ChromeProvider()
plugin.verify_account(p.data,plugin.expected_account())
assert p._chrome_processes(),'original Chrome not running'
port,path=(p.data/'DevToolsActivePort').read_text().splitlines()[:2]
w=Wire('ws://127.0.0.1:'+port+path,str(p.data))
try:targets=w('Target.getTargets')['targetInfos']
finally:w.close()
b=json.loads((ROOT/'RESUME-PRODUCTION-baseline.json').read_text());g=json.loads((ROOT/'RESUME-PRODUCTION-green.json').read_text())
ids={i['targetId'] for i in targets}
before={i['target'] for i in b['trace'][0].get('inventory',[]) if i['type']=='page'}
owned=set(g['ownership'][0]['state']['owned'])
first_inventory=next(t['inventory'] for t in b['trace'] if 'inventory'in t)
before={i['target'] for i in first_inventory if i['type']=='page'}
result={'green_owned_absent':not bool(owned&ids),'green_owned_target_ids':sorted(owned),'all_baseline_pages_preserved':before<=ids,'missing_baseline_pages':sorted(before-ids),'failed_baseline_seed_preserved':set(b['ownership'][0]['state']['owned'])<=ids,'inventory':[{'target':i['targetId'],'type':i.get('type'),'url_kind':i.get('url','').split(':',1)[0],'attached':i.get('attached')} for i in targets]}
assert result['green_owned_absent'] and result['all_baseline_pages_preserved'] and result['failed_baseline_seed_preserved'],result
(ROOT/'RESUME-CLEANUP-READBACK.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='inventory'},indent=2))
snap=ROOT/'snapshot-resume-20261018-2235'
diff=''
for name,old in [('observer.py',snap/'observer.py'),('tests/test_observer.py',snap/'test_observer.py'),('tests/test_resume_setup.py',None),('tests/live_resume_production.py',None),('tests/verify_resume_cleanup.py',None)]:
    diff+=''.join(difflib.unified_diff(old.read_text().splitlines(True) if old else [],(ROOT/name).read_text().splitlines(True),fromfile='before/'+name,tofile='after/'+name))
(ROOT/'evidence-resume-scoped.diff').write_text(diff)
print('unchanged_other_production',all((ROOT/f).read_bytes()==(snap/f).read_bytes() for f in ('worker.py','plugin.py')))
