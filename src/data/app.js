document.addEventListener('DOMContentLoaded', function () {
    showTab('wifi');
    scanWifi();

    // Before submitting, copy the manually typed SSID into the select
    document.getElementById('wifi-form').addEventListener('submit', function (e) {
        var select = document.getElementById('ssid-select');
        if (select.value === '__other__') {
            var manual = document.getElementById('ssid-manual').value.trim();
            if (!manual) {
                e.preventDefault();
                document.getElementById('ssid-manual').focus();
                return;
            }
            var opt = document.createElement('option');
            opt.value = manual;
            select.appendChild(opt);
            select.value = manual;
        }
    });
});

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(function (el) {
        el.classList.add('hidden');
    });
    document.querySelectorAll('.tab-btn').forEach(function (btn) {
        btn.classList.remove('text-indigo-600', 'border-indigo-600');
        btn.classList.add('text-gray-500', 'border-transparent');
    });
    var content = document.getElementById('tab-' + tabName);
    if (content) content.classList.remove('hidden');
    var btn = document.querySelector('.tab-btn[data-tab="' + tabName + '"]');
    if (btn) {
        btn.classList.remove('text-gray-500', 'border-transparent');
        btn.classList.add('text-indigo-600', 'border-indigo-600');
    }
    if (tabName === 'status') {
        refreshStatus();
    }
}

function refreshStatus() {
    var btn = document.getElementById('refresh-ip-btn');
    btn.disabled = true;
    btn.textContent = 'Refreshing...';
    document.getElementById('public-ip-display').textContent = '…';

    var fetchIp = fetch('/refresh-ip', { method: 'POST' })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            document.getElementById('public-ip-display').textContent = data.ip || 'unknown';
            document.getElementById('public-ip-updated').textContent =
                'Last checked: ' + new Date().toLocaleTimeString();
        })
        .catch(function () {
            document.getElementById('public-ip-display').textContent = 'error';
            document.getElementById('public-ip-updated').textContent = 'Could not fetch IP';
        });

    var fetchCf = loadCfStatus();

    Promise.all([fetchIp, fetchCf]).finally(function () {
        btn.disabled = false;
        btn.textContent = 'Refresh';
    });
}

function loadCfStatus() {
    var cfStatusEl   = document.getElementById('cf-status-display');
    var zoneIpEl     = document.getElementById('zone-ip-display');
    var lastUpdateEl = document.getElementById('last-dns-update-display');

    return fetch('/cf-status')
        .then(function (res) { return res.json(); })
        .then(function (data) {
            var s = data.cf_status || 'unknown';
            cfStatusEl.textContent = s;
            cfStatusEl.className = 'font-semibold ' + (
                s === 'valid'        ? 'text-green-600'  :
                s === 'invalid'      ? 'text-red-600'    :
                s === 'unconfigured' ? 'text-yellow-600' :
                                       'text-gray-500'
            );
            zoneIpEl.textContent     = data.zone_ip         || 'unknown';
            lastUpdateEl.textContent = data.last_dns_update || 'never';
        })
        .catch(function () {
            cfStatusEl.textContent   = 'error';
            zoneIpEl.textContent     = '—';
            lastUpdateEl.textContent = '—';
        });
}

function togglePassword(inputId, btn) {
    var input = document.getElementById(inputId);
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = 'Hide';
    } else {
        input.type = 'password';
        btn.textContent = 'Show';
    }
}

function onSsidChange() {
    var select = document.getElementById('ssid-select');
    var wrap   = document.getElementById('ssid-manual-wrap');
    if (select.value === '__other__') {
        wrap.classList.remove('hidden');
        document.getElementById('ssid-manual').focus();
    } else {
        wrap.classList.add('hidden');
    }
}

function scanWifi() {
    var select = document.getElementById('ssid-select');
    var btn    = document.getElementById('scan-btn');

    btn.disabled = true;
    btn.textContent = 'Scanning...';
    select.innerHTML = '<option value="">Scanning for networks...</option>';
    document.getElementById('ssid-manual-wrap').classList.add('hidden');

    fetch('/scan-wifi')
        .then(function (res) { return res.json(); })
        .then(function (ssids) {
            if (ssids.length) {
                select.innerHTML = '<option value="">-- Select a network --</option>';
                ssids.forEach(function (ssid) {
                    var opt = document.createElement('option');
                    opt.value = ssid;
                    opt.textContent = ssid;
                    select.appendChild(opt);
                });
            } else {
                select.innerHTML = '<option value="">No networks found</option>';
            }
            var other = document.createElement('option');
            other.value = '__other__';
            other.textContent = 'Other (hidden network)...';
            select.appendChild(other);
        })
        .catch(function () {
            select.innerHTML = '<option value="__other__">Scan failed — enter manually</option>';
            onSsidChange();
        })
        .finally(function () {
            btn.disabled = false;
            btn.textContent = 'Refresh';
        });
}
