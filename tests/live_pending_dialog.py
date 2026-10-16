"""Source acceptance: beforeunload yields without replay; disposable GUI only."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
from worker import Wire
import psutil

def main():
    work=Path(tempfile.mkdtemp(prefix='chrome-pending-dialog-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir();provider=ChromeProvider(data=data,workspace=work/'work');control=None
    out={'level':'source direct provider; not installed/native chat','personal_profile_used':False,'decisions':[]}
    def execute(code):return json.loads(provider.execute({'code':code,'timeout_s':12},task_id='pending'))
    def checked(code):
        result=execute(code);assert result['success'],result;return result
    try:
        url='data:text/html,<button style="width:500px;height:200px">activate</button>'
        checked('new_tab('+repr(url)+');wait_for_load()\ncdp("Input.dispatchMouseEvent",type="mousePressed",x=50,y=50,button="left",clickCount=1)\ncdp("Input.dispatchMouseEvent",type="mouseReleased",x=50,y=50,button="left",clickCount=1)\njs("window.leaves=0;window.onbeforeunload=(e)=>{leaves++;e.preventDefault();e.returnValue=\'\';return \'\'}")')
        entry=provider.states[('pending','default')];control=Wire(entry['endpoint'])
        comparator=control('Target.createTarget',{'url':'about:blank','newWindow':True,'browserContextId':entry['state']['context']})['targetId']
        window=control('Browser.getWindowForTarget',{'targetId':comparator})['windowId']
        observer=entry['observer'];original=observer.wire.ws.send;sent=[]
        def send(text,*args,**kwargs):
            sent.append(json.loads(text)['method']);return original(text,*args,**kwargs)
        observer.wire.ws.send=send
        for accept in (False,True):
            started=time.monotonic();result=execute('cdp("Page.navigate",url="about:blank")')
            assert not result['success'] and 'dialog_pending' in result.get('error',''),result
            assert not entry.get('uncertain'),entry
            assert time.monotonic()-started<5,result
            observed=checked('print(page_info())');assert 'beforeunload' in observed['stdout'],observed
            answer=checked('cdp("Page.handleJavaScriptDialog",accept='+repr(accept)+');print(page_info())')
            if not accept:assert checked('print(js("window.leaves"))')['stdout'].strip()=='1'
            else:assert "'url': 'about:blank'" in answer['stdout'],answer
            out['decisions'].append({'accept':accept,'success':True})
        assert sent.count('Page.navigate')==2,sent # Two explicit requests, neither replayed.
        cleanup=json.loads(checked('import json;print(json.dumps(finish_browser()))')['stdout'])
        assert cleanup['success'] and not cleanup['remaining_owned_targets'],cleanup
        assert cleanup['browser_closed'] and not provider._chrome_processes(),cleanup
        out.update(cleanup=cleanup,explicit_navigations=2,actual_navigations=sent.count('Page.navigate'),browser_process_exited=True,success=True)
    finally:
        provider.close_session('pending')
        if control:
            try:control('Browser.close') # Disposable root ONLY.
            except Exception:pass
            control.close()
        deadline=time.monotonic()+5
        while True:
            residue=[p.pid for p in psutil.process_iter(['cmdline'])if '--user-data-dir='+str(data)in(p.info['cmdline']or[])]
            if not residue or time.monotonic()>=deadline:break
            time.sleep(.1)
        out['fixture_process_residue']=residue
        (ROOT/'PENDING-DIALOG-RESULT.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
        assert not residue
if __name__=='__main__':main()
