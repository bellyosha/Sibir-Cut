"""LAN regressions: loopback SSDP and mock MQTT; never contact a printer."""
from __future__ import annotations

import json
import socket
import threading
from types import SimpleNamespace
from unittest.mock import patch

from . import discovery, lan, printer_manager


def _check(condition, message):
    if not condition:
        raise RuntimeError(message)


def _reject(operation, fragment):
    try:
        operation()
    except lan.BambuLanError as exc:
        _check(fragment in str(exc), f'Unexpected LAN diagnostic: {exc}')
        return
    raise RuntimeError('Invalid LAN connection was accepted')


class _Event:
    """Synchronous fake callbacks avoid waiting eight seconds for each failure."""
    def __init__(self):self.value=False
    def clear(self):self.value=False
    def set(self):self.value=True
    def wait(self, timeout=None):return self.value


class _MQTT:
    actual_serial='TEST-PRINTER-01'
    def __init__(self, mode='good'):
        self.mode=mode;self.published=[];self.subscribed=[];self.unsubscribed=[];self.stopped=False
    def username_pw_set(self, *args):pass
    def tls_set(self, **kwargs):pass
    def tls_insecure_set(self, value):pass
    def connect(self, host, port, **kwargs):
        _check(port==8883, 'LAN changed from protected MQTT port')
        if self.mode=='refused':raise ConnectionRefusedError(10061, 'refused')
    def subscribe(self, topic, **kwargs):
        self.subscribed.append(topic)
        if self.mode=='subscription-denied':
            self.on_subscribe(self,None,1,[SimpleNamespace(value=128)],None)
        return (0,1)
    def unsubscribe(self, topic):self.unsubscribed.append(topic)
    def loop_start(self):
        rc=135 if self.mode=='bad-code' else 0
        self.on_connect(self,None,None,SimpleNamespace(value=rc),None)
        if rc==0 and self.mode in ('good','wrong-serial'):
            message=SimpleNamespace(topic=f'device/{self.actual_serial}/report',payload=json.dumps({'print':{'gcode_state':'IDLE','nozzle_temper':25}}).encode())
            self.on_message(self,None,message)
    def publish(self, topic, payload, **kwargs):
        self.published.append((topic,json.loads(payload)))
        return SimpleNamespace(rc=0)
    def disconnect(self):self.on_disconnect(self,None)
    def loop_stop(self):self.stopped=True


def _client(mode='good', serial=''):
    broker=_MQTT(mode)
    library=SimpleNamespace(Client=lambda *args,**kwargs:broker,CallbackAPIVersion=SimpleNamespace(VERSION2=2),MQTTv311=4,MQTT_ERR_SUCCESS=0)
    with patch.object(lan,'mqtt',library):
        client=lan.BambuLanClient('127.0.0.1','test-code',serial)
    client._report_event=_Event()
    return client,broker


def run_lan_checks():
    packet='HTTP/1.1 200 OK\r\nST: '+discovery.BAMBU_NT+'\r\nLocation: 127.0.0.1\r\nDevModel.bambu.com: N2S\r\nUSN: uuid:TEST-PRINTER-01::'+discovery.BAMBU_NT+'\r\n\r\n'
    parsed=discovery.parse_bambu_ssdp(packet)
    _check(parsed.serial=='TEST-PRINTER-01' and parsed.model_name=='Bambu Lab A1', 'SSDP UUID prefix/suffix was not removed')
    generic=packet.replace('uuid:TEST-PRINTER-01','uuid:12345678-1234-1234-1234-123456789abc')
    _check(discovery.parse_bambu_ssdp(generic).serial=='', 'Generic UPnP UUID became a printer serial')
    explicit=generic.replace('USN:', 'DevSerial.bambu.com: REAL-SERIAL\r\nUSN:')
    _check(discovery.parse_bambu_ssdp(explicit).serial=='REAL-SERIAL', 'Explicit SSDP serial was ignored')
    _check('не подтверждённый принтер' in discovery.discovery_identity_hint(discovery.DiscoveredPrinter('127.0.0.1',source='tcp')), 'TCP candidate was described as an identified printer')

    # A real UDP peer replies to the ephemeral M-SEARCH source port.
    found=[];failures=[]
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as peer:
        peer.bind(('127.0.0.1',0));peer.settimeout(2)
        def respond():
            try:
                data,address=peer.recvfrom(8192)
                _check(data.startswith(b'M-SEARCH'), 'No SSDP search was sent')
                peer.sendto(packet.encode(),address)
            except Exception as exc:failures.append(exc)
        thread=threading.Thread(target=respond,daemon=True);thread.start()
        scanner=discovery.BambuLanScanner(on_printer=lambda printer:(found.append(printer),scanner.stop()))
        with patch.object(discovery,'SSDP_GROUP','127.0.0.1'),patch.object(discovery,'SSDP_PORTS',(peer.getsockname()[1],)),patch.object(discovery,'_local_ipv4_addresses',return_value=['127.0.0.1']),patch.object(discovery.BambuLanScanner,'_make_listener',return_value=None):
            scanner._listen_ssdp(1.5)
        thread.join(2)
    _check(not failures and not thread.is_alive() and len(found)==1 and found[0].serial=='TEST-PRINTER-01', 'Unicast SSDP reply to source port was lost')
    scanner=discovery.BambuLanScanner()
    scanner._emit(discovery.DiscoveredPrinter('127.0.0.1',source='tcp'))
    scanner._emit(discovery.DiscoveredPrinter('127.0.0.1',model_code='N2S',source='ssdp'))
    scanner._emit(parsed)
    scanner._emit(discovery.DiscoveredPrinter('127.0.0.1',model_code='N2S',source='ssdp'))
    _check(len(scanner.snapshot())==1 and scanner.snapshot()[0].serial=='TEST-PRINTER-01', 'Discovery retained duplicate TCP/SSDP rows')

    client,broker=_client(mode='no-report',serial='TEST-PRINTER-01')
    client._handle_connect(broker,None,None,0)
    _check(not client.connected, 'Broker login became a verified printer connection')
    _reject(lambda:client.send_gcode('G90'),'Нет подключения')
    for payload in (b'{}',b'{"print":{}}',b'not-json'):
        client._handle_message(broker,None,SimpleNamespace(topic='device/TEST-PRINTER-01/report',payload=payload))
    _check(not client.connected, 'Invalid report verified a printer')
    client.close()

    for serial in ('','TEST-PRINTER-01'):
        client,broker=_client(serial=serial)
        _reject(lambda:client.send_gcode('G90'),'Нет подключения')
        client.connect(timeout=1)
        _check(client.connected and client.serial==broker.actual_serial, 'MQTT report did not verify actual serial')
        _check(client.report_topic=='device/TEST-PRINTER-01/report', 'Wildcard identity was not bound to one printer')
        _check(all(topic=='device/TEST-PRINTER-01/request' and set(payload)=={'pushing'} for topic,payload in broker.published), 'Identification sent a control or job-start command')
        if not serial:
            _check(broker.subscribed==['device/+/report','device/TEST-PRINTER-01/report'] and broker.unsubscribed==['device/+/report'], 'Wildcard subscription remained active')
        client._handle_message(broker,None,SimpleNamespace(topic='device/ANOTHER/report',payload=b'{"print":{"gcode_state":"RUNNING"}}'))
        _check(client.status_summary()['gcode_state']=='IDLE', 'Another serial changed active printer state')
        client.close();_check(not client.connected and broker.stopped, 'MQTT client was not closed')
    for mode,serial,hint in [('refused','','10061'),('bad-code','','LAN access code'),('subscription-denied','','вручную'),('no-report','','Serial не получен'),('wrong-serial','WRONG-SERIAL','нет статуса')]:
        client,broker=_client(mode,serial)
        _reject(lambda:client.connect(timeout=1),hint)
        _check(not client.connected and broker.stopped, 'Failed connection left a network client active')
    for exc,expected in [(TimeoutError(),'время ожидания'),(socket.gaierror(),'адрес'),(ConnectionRefusedError(),'Пароль и Serial ещё не проверялись')]:
        _check(expected in lan.connection_error_text('127.0.0.1',exc), 'Network error categories were confused')
    class OpenSocket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    with patch.object(lan.socket,'create_connection',side_effect=[ConnectionRefusedError(),OpenSocket()]) as mocked:
        text=lan.check_lan_services('127.0.0.1')
    _check(mocked.call_count==2 and '8883: соединение отклонено' in text and '990: TCP доступен' in text and 'Access code, Serial' in text, 'LAN diagnostics mixed network and authentication')

    # An empty form serial must be replaced by the verified serial before save.
    client,broker=_client()
    class App:
        _lan_client=None
        project=SimpleNamespace(printer=SimpleNamespace(model='A1',serial='TEST-PRINTER-01'))
        def after(self, delay, callback):callback()
        def set_printer_status(self, *args):pass
    app=App();saved=[]
    with patch.object(printer_manager,'BambuLanClient',return_value=client),patch.object(printer_manager,'load_lan_config',return_value={}),patch.object(printer_manager,'_load_tool_calibrations'),patch.object(printer_manager,'_save_printer_record',side_effect=lambda cfg,record,*args:(saved.append(dict(record)) or {})):
        _check(printer_manager.connect_printer(app,{'host':'127.0.0.1','serial':'','model':'Bambu Lab A1'},'test-code',quiet=True), 'Manager rejected auto serial')
    _check(saved[0]['serial']=='TEST-PRINTER-01', 'Manager saved an empty or stale serial')
    client.close()
    print('LAN discovery, unicast SSDP, auto serial, verified status and connection diagnostics OK')


def lan_dialog_self_test(app):
    """Open both connection dialogs offline, including their new callbacks."""
    from . import lan_gui
    class OfflineScanner:
        def __init__(self,**kwargs):pass
        def scan(self,*args):return []
        def stop(self):pass
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    for module,opener,attribute in ((printer_manager,printer_manager.open_printer_manager,'_printer_manager_window'),(lan_gui,lan_gui.open_lan_control,'_lan_window')):
        with patch.object(module,'load_lan_config',return_value={}),patch.object(module,'save_lan_config'),patch.object(module,'BambuLanScanner',OfflineScanner):
            opener(app)
            window=getattr(app,attribute)
            try:
                app.update_idletasks()
                buttons=[w for w in widgets(window) if 'text' in w.keys() and w.cget('text')=='Проверить LAN']
                _check(len(buttons)==1 and buttons[0].cget('command'), 'LAN diagnostic button or callback missing')
            finally:
                window.tk.call(window.protocol('WM_DELETE_WINDOW'))


if __name__=='__main__':
    run_lan_checks()
