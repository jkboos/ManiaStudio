"""Windows job ownership: closing the launcher kills its complete worker tree."""
import ctypes
from ctypes import wintypes as W
import subprocess
import sys

kernel = ctypes.WinDLL('kernel32',use_last_error=True)


class BasicLimits(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),
              ('LimitFlags',W.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),
              ('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',W.DWORD),
              ('Affinity',ctypes.c_size_t),('PriorityClass',W.DWORD),('SchedulingClass',W.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_=[(name,ctypes.c_ulonglong) for name in ('ReadOperationCount','WriteOperationCount',
               'OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]


class ExtendedLimits(ctypes.Structure):
    _fields_=[('BasicLimitInformation',BasicLimits),('IoInfo',IoCounters),
              ('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),
              ('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]


kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];kernel.CreateJobObjectW.restype=W.HANDLE
kernel.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD];kernel.SetInformationJobObject.restype=W.BOOL
kernel.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];kernel.AssignProcessToJobObject.restype=W.BOOL
kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL


class ProcessTree:
    def __init__(self):
        self.handle=kernel.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        info=ExtendedLimits();info.BasicLimitInformation.LimitFlags=0x2000 # KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            error=ctypes.WinError(ctypes.get_last_error());self.close();raise error

    def start(self,script,args=(),**kwargs):
        # The child waits before importing the server or spawning any workers,
        # so assignment cannot race with descendant creation.
        gate="import sys,runpy; sys.stdin.readline(); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
        child=subprocess.Popen([sys.executable,'-u','-c',gate,str(script),*map(str,args)],stdin=subprocess.PIPE,**kwargs)
        try:
            if not kernel.AssignProcessToJobObject(self.handle,W.HANDLE(int(child._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            child.stdin.write(b'go\n');child.stdin.flush();child.stdin.close()
        except BaseException:
            child.kill();child.wait();raise
        return child

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle);self.handle=None


def launcher_mutex(name):
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
    handle=kernel.CreateMutexW(None,False,name)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    return handle,ctypes.get_last_error()!=183 # ERROR_ALREADY_EXISTS
