const $ = id => document.getElementById(id);
const set = (id, value) => { $(id).textContent = value ?? 'N/A'; };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

let pollingPaused = false;
let refreshRunning = false;
let detailRefreshCounter = 0;

const duration = seconds => {
  seconds = Number(seconds) || 0;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${days}d ${hours}h ${minutes}m`;
};

const bytes = value => value == null ? 'N/A' :
  value > 1048576 ? (value / 1048576).toFixed(1) + ' MB' :
  Math.round(value / 1024) + ' KB';

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw Error(response.status);
  return response.json();
}

function safe(value) {
  const element = document.createElement('span');
  element.textContent = value ?? '';
  return element.innerHTML;
}

function drawDevices(devices) {
  $('deviceRows').innerHTML = devices.map(device =>
    `<tr><td>${safe(device.device_name)}</td><td>${safe(device.node_id)}</td>` +
    `<td>${safe(device.ip_address)}</td><td>${safe(device.last_seen)}</td>` +
    `<td>${device.packet_count}</td></tr>`
  ).join('') || '<tr><td colspan="5">No devices observed</td></tr>';
}

function drawLogs(logs) {
  $('logs').innerHTML = logs.slice().reverse().map(log =>
    `<div class="log ${log.level}"><span>${safe(log.timestamp)}</span>` +
    `<b>${log.level}</b> ${safe(log.message)}</div>`
  ).join('');
}

async function refresh() {
  if (pollingPaused || refreshRunning) return;
  refreshRunning = true;
  try {
    const snapshot = await api('/api/snapshot');
    const s = snapshot.status;
    const n = snapshot.network;
    const t = snapshot.statistics;
    const x = s.lte || {};

    set('gatewayName', s.gateway_name);
    set('gatewayStatus', s.gateway_status);
    set('uptime', duration(s.uptime_seconds));
    set('memory', bytes(s.free_memory));
    set('cpu', s.cpu_usage == null ? 'N/A' : s.cpu_usage + '%');
    set('tcpStatus', s.tcp_server);
    set('httpStatus', s.http_server);
    set('mqttStatus', s.mqtt_status);
    set('cloudStatus', s.cloud_status);
    set('firmware', s.firmware_version);
    set('systemTime', (s.time_synchronized ? 'NTP ' : 'RTC ') + s.system_time);

    set('lteStatus', !x.enabled ? 'DISABLED' :
      x.internet_ok ? 'INTERNET OK' :
      x.data_active ? 'LTE ONLINE' : (x.registration || 'STARTING'));
    set('lteOperator', (x.operator || 'Unknown operator') +
      ' · SIM ' + (x.sim_status || 'UNKNOWN'));
    set('lteSignal', x.signal_dbm == null ? 'N/A' : x.signal_dbm + ' dBm');
    set('lteIp', x.internet_ok ? `Ping ${x.ping_latency_ms} ms` :
      x.mobile_ip ? `IP ${x.mobile_ip}` : `APN ${x.apn || '—'}`);

    set('wifiStatus', n.wifi_status);
    set('wifiRssi', n.wifi_rssi == null ? 'RSSI unavailable' : n.wifi_rssi + ' dBm');
    set('ipAddress', n.ip_address);
    set('packets', t.packets_received);
    set('rate', t.packets_per_second + ' packets/s');
    set('clients', t.connected_clients);
    set('devicesCount', t.known_devices + ' known devices');
    set('lastIp', t.last_client_ip);
    set('lastTime', t.last_receive_time);
    set('lastJson', t.last_json_received);
    if (detailRefreshCounter <= 0) {
      const details = await api('/api/details');
      drawDevices(details.devices);
      drawLogs(details.logs);
      // Devices and logs change slowly; refresh them about every 15 seconds.
      detailRefreshCounter = 15;
    } else {
      detailRefreshCounter--;
    }
    set('updated', 'Updated ' + new Date().toLocaleTimeString());
    $('health').textContent = 'Operational';
  } catch (error) {
    set('gatewayStatus', 'OFFLINE');
    $('health').textContent = 'Connection lost';
    console.error('Dashboard refresh failed:', error);
  } finally {
    refreshRunning = false;
  }
}

$('lteTest').onclick = async () => {
  const button = $('lteTest');
  button.disabled = true;
  button.textContent = 'Testing…';
  pollingPaused = true;
  try {
    await api('/api/lte/test', {method: 'POST'});
    let result = null;
    for (let attempt = 0; attempt < 20; attempt++) {
      await wait(1000);
      const status = await api('/api/status');
      if (!status.lte.internet_test_running) {
        result = status.lte;
        break;
      }
    }
    if (!result) throw Error('test timeout');
    alert(result.internet_ok ?
      `4G internet OK\nPing: ${result.ping_latency_ms} ms\nHost: ${result.ping_host}` :
      `4G internet test failed\nHost: ${result.ping_host}`);
  } catch (error) {
    alert('4G test failed: ' + error.message);
  } finally {
    pollingPaused = false;
    button.disabled = false;
    button.textContent = 'Test 4G';
    refresh();
  }
};

$('restart').onclick = async () => {
  if (confirm('Restart the gateway now?')) {
    await api('/api/restart', {method: 'POST'}).catch(() => {});
    set('gatewayStatus', 'RESTARTING');
  }
};

refresh();
setInterval(refresh, 1000);
