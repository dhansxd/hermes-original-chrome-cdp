"""AX object graph for consent unit tests; never loads a native framework."""
import ctypes
from unittest.mock import Mock
import consent


def exact_sheet():
    ax=object.__new__(consent.AX)
    ax.refs=[];ax.deadline=None;ax.c=ctypes
    ax.ax=Mock();ax.cf=Mock()
    ax.ax.AXUIElementSetMessagingTimeout.return_value=0
    ax.ax.AXUIElementPerformAction.return_value=0
    def pid(node,out):
        out._obj.value=42
        return 0
    ax.ax.AXUIElementGetPid.side_effect=pid
    ax.cf.CFEqual.side_effect=lambda a,b:a==b
    ax.cf.CFHash.side_effect=lambda node:node*100
    ax.string=lambda text:text
    data={1:{'AXRole':'AXWindow'},2:{'AXRole':'AXSheet','AXTitle':'Allow remote debugging?'},
          3:{'AXRole':'AXHeading','AXValue':'Allow remote debugging?'},
          4:{'AXRole':'AXButton','AXTitle':'Allow'},5:{'AXRole':'AXButton','AXTitle':'Cancel'}}
    ax.text=lambda node,key:data.get(node,{}).get(key,'')
    ax.children=lambda node:{1:[2],2:[3,4,5]}.get(node,[])
    ax.attr=lambda node,key:{2:1,3:2,4:2,5:2}.get(node) if key=='AXParent' else None
    ax.geometry_state=lambda sheet:((1000,700),(500,300))
    ax.mouse_down=lambda:False
    sheet=ax.describe_sheet(2,42,1)
    sheet['host']={'started':1,'exe':'/fixture/chrome','kind':'main','bound':True}
    return ax,sheet,data
