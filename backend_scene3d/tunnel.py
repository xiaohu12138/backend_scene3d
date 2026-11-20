"""Loopback-only SSH forward with pinned host key and Windows DPAPI credentials."""
import os
import socketserver
import subprocess
import threading
import time
import shlex
from pathlib import Path
import paramiko
from dotenv import load_dotenv
from .config import ROOT

def password():
    path=ROOT/'.local/ssh-password.xml'
    if os.name!='nt':return os.environ.get('SCENE3D_SSH_PASSWORD')
    # DPAPI encrypts this file for the current Windows user. Never print its plaintext.
    script="$s=Import-Clixml -LiteralPath '"+str(path).replace("'","''")+"'; [System.Net.NetworkCredential]::new('', $s).Password"
    return subprocess.check_output(['powershell.exe','-NoProfile','-Command',script],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip()

def main():
    load_dotenv(ROOT/'.env'); host=os.environ['SCENE3D_SSH_HOST']
    client=paramiko.SSHClient(); client.load_host_keys(str(ROOT/'.local/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    class Forward(socketserver.BaseRequestHandler):
        def handle(self):
            import select
            try:
                transport=client.get_transport()
                if not transport or not transport.is_active():return
                channel=transport.open_channel('direct-tcpip',('127.0.0.1',8013),self.client_address,timeout=8)
                with channel:
                    while True:
                        ready,_,_=select.select([self.request,channel],[],[],30)
                        for source in ready:
                            data=source.recv(65536)
                            if not data:return
                            (channel if source is self.request else self.request).sendall(data)
            except (OSError,EOFError,paramiko.SSHException):return
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    last_ensure=0
    with Server(('127.0.0.1',18013),Forward) as server:
        threading.Thread(target=server.serve_forever,daemon=True).start()
        while True:
            try:
                transport=client.get_transport()
                if not transport or not transport.is_active():
                    client.connect(host,port=int(os.environ.get('SCENE3D_SSH_PORT','22')),
                        username=os.environ['SCENE3D_SSH_USER'],password=password(),look_for_keys=False,
                        allow_agent=False,timeout=10,auth_timeout=10,banner_timeout=10)
                    client.get_transport().set_keepalive(20)
                    last_ensure=0
                    print('Scene3D SSH forward ready: 127.0.0.1:18013 -> server:8013',flush=True)
                # The server may restart while SSH stays connected. Re-run only
                # our idempotent managed start script, never an arbitrary command.
                if time.monotonic()-last_ensure>=30:
                    project=os.environ.get('SCENE3D_REMOTE_PROJECT','')
                    interpreter=os.environ.get('SCENE3D_REMOTE_PYTHON','')
                    if project and interpreter:
                        command='SCENE3D_PYTHON='+shlex.quote(interpreter)+' bash '+shlex.quote(project+'/scripts/start-server.sh')
                        _,output,error=client.exec_command(command,timeout=12)
                        status=output.channel.recv_exit_status()
                        if status:print('Scene3D managed server startup failed; inspect its server log.',flush=True)
                    last_ensure=time.monotonic()
            except (OSError,paramiko.SSHException):
                print('Scene3D SSH connection unavailable; retrying in 5 seconds.',flush=True)
            time.sleep(5)

if __name__=='__main__':main()
