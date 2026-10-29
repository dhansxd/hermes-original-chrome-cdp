"""Completed research output survives a killed worker via its existing pipe."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from worker import ProgressOutput


class WorkerProgressTests(unittest.TestCase):
    def test_progress_contains_only_bounded_stdout_after_completed_writes(self):
        frames=[];out=ProgressOutput(frames.append)
        out.write('completed finding\n')
        self.assertEqual(frames,[{'stdout':'completed finding\n'}])
        out.write('x'*25000)
        self.assertEqual(set(frames[-1]),{'stdout'})
        self.assertEqual(len(frames[-1]['stdout']),20000)
        self.assertEqual(len(out.getvalue()),20000)

    def test_real_pipe_progress_survives_termination_before_final_result(self):
        with tempfile.TemporaryDirectory() as workspace:
            process=subprocess.Popen([sys.executable,str(ROOT/'worker.py')],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            frames=queue.Queue();seen=[]
            def read():
                try:
                    for line in process.stdout:frames.put(json.loads(line))
                finally:frames.put(None)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            try:
                request={'endpoint':'ws://synthetic-unused','profile':'/synthetic/Default',
                    'workspace':workspace,'parent_transport':True,
                    'state':{'context':'ctx','current':'owned','owned':{'owned':7},'verified':True},
                    'code':"print('completed research finding')\nwait(30)\nprint('not completed')"}
                process.stdin.write(json.dumps(request)+'\n');process.stdin.flush()
                for _ in range(40):
                    frame=frames.get(timeout=3)
                    self.assertIsNotNone(frame,'worker ended before publishing its completed research')
                    seen.append(frame)
                    if 'progress' in frame:break
                    if 'cdp' in frame:
                        method=frame['cdp']['method']
                        if method=='Target.getTargets':
                            value={'targetInfos':[{'targetId':'owned','type':'page','browserContextId':'ctx','url':'https://example.test'}]}
                        elif method=='Browser.getWindowForTarget':value={'windowId':7}
                        elif method=='Target.attachToTarget':value={'sessionId':'held'}
                        else:value={}
                        process.stdin.write(json.dumps({'value':value,'events':[],'dialogs':{},
                            'event_overflow':False,'event_gaps':{}})+'\n');process.stdin.flush()
                else:self.fail('worker did not publish output within bounded protocol steps')
                process.terminate();process.wait(timeout=3);reader.join(1)
                self.assertEqual(frame['progress'],{'stdout':'completed research finding\n'})
                self.assertFalse(any('result' in frame for frame in seen),'test must terminate before final result')
                self.assertNotIn('not completed',json.dumps(seen))
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=3)
                process.stdin.close();reader.join(1);process.stdout.close()


if __name__=='__main__':unittest.main()
