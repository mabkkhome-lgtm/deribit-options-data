// ==UserScript==
// @name         Options Levels Auto-Update
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  Automatically updates the Options Levels Tracker indicator with latest resistance/support values
// @author       Thales Bot
// @match        https://www.tradingview.com/*
// @match        https://tradingview.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      raw.githubusercontent.com
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    // ═══════════════════════════════════════════════════════════════════════════════
    // CONFIGURATION
    // ═══════════════════════════════════════════════════════════════════════════════

    const CONFIG = {
        dataUrl: 'https://raw.githubusercontent.com/mabkkhome-lgtm/deribit-options-data/main/data/btc_levels.csv',
        updateIntervalMs: 5 * 60 * 1000, // Check every 5 minutes
        indicatorName: 'Options Levels',
        showNotifications: true
    };

    // ═══════════════════════════════════════════════════════════════════════════════
    // STATE
    // ═══════════════════════════════════════════════════════════════════════════════

    let state = {
        resistance: 0,
        support: 0,
        lastUpdate: null,
        isUpdating: false
    };

    // ═══════════════════════════════════════════════════════════════════════════════
    // UI - Status Panel
    // ═══════════════════════════════════════════════════════════════════════════════

    function createStatusPanel() {
        // Remove existing panel if any
        const existing = document.getElementById('options-levels-panel');
        if (existing) existing.remove();

        const panel = document.createElement('div');
        panel.id = 'options-levels-panel';
        panel.innerHTML = `
            <div class="ol-header">
                <span class="ol-title">📊 Options Levels</span>
                <button class="ol-refresh" title="Refresh Now">↻</button>
            </div>
            <div class="ol-content">
                <div class="ol-row">
                    <span class="ol-label">Resistance:</span>
                    <span class="ol-value ol-green" id="ol-resistance">--</span>
                </div>
                <div class="ol-row">
                    <span class="ol-label">Support:</span>
                    <span class="ol-value ol-red" id="ol-support">--</span>
                </div>
                <div class="ol-status" id="ol-status">Loading...</div>
            </div>
        `;

        // Styles
        const style = document.createElement('style');
        style.textContent = `
            #options-levels-panel {
                position: fixed;
                bottom: 80px;
                right: 20px;
                background: rgba(30, 34, 45, 0.95);
                border: 1px solid #363a45;
                border-radius: 8px;
                padding: 0;
                z-index: 9999;
                font-family: -apple-system, BlinkMacSystemFont, 'Trebuchet MS', sans-serif;
                font-size: 13px;
                color: #d1d4dc;
                min-width: 180px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                user-select: none;
            }
            .ol-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 12px;
                background: rgba(41, 98, 255, 0.15);
                border-radius: 8px 8px 0 0;
                border-bottom: 1px solid #363a45;
            }
            .ol-title {
                font-weight: 600;
                font-size: 12px;
            }
            .ol-refresh {
                background: none;
                border: none;
                color: #787b86;
                cursor: pointer;
                font-size: 16px;
                padding: 2px 6px;
                border-radius: 3px;
            }
            .ol-refresh:hover {
                background: rgba(255,255,255,0.1);
                color: #d1d4dc;
            }
            .ol-content {
                padding: 10px 12px;
            }
            .ol-row {
                display: flex;
                justify-content: space-between;
                margin-bottom: 6px;
            }
            .ol-label {
                color: #787b86;
            }
            .ol-value {
                font-weight: 600;
                font-family: 'Monaco', 'Menlo', monospace;
            }
            .ol-green { color: #26a69a; }
            .ol-red { color: #ef5350; }
            .ol-status {
                font-size: 10px;
                color: #787b86;
                text-align: center;
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px solid #363a45;
            }
            .ol-status.success { color: #26a69a; }
            .ol-status.error { color: #ef5350; }
        `;
        document.head.appendChild(style);
        document.body.appendChild(panel);

        // Refresh button handler
        panel.querySelector('.ol-refresh').addEventListener('click', () => {
            fetchAndUpdate();
        });

        return panel;
    }

    function updateStatusPanel() {
        const resEl = document.getElementById('ol-resistance');
        const supEl = document.getElementById('ol-support');
        const statusEl = document.getElementById('ol-status');

        if (resEl) resEl.textContent = '$' + state.resistance.toLocaleString();
        if (supEl) supEl.textContent = '$' + state.support.toLocaleString();
        if (statusEl) {
            statusEl.textContent = 'Updated: ' + new Date().toLocaleTimeString();
            statusEl.className = 'ol-status success';
        }
    }

    function setStatus(text, isError = false) {
        const statusEl = document.getElementById('ol-status');
        if (statusEl) {
            statusEl.textContent = text;
            statusEl.className = 'ol-status ' + (isError ? 'error' : '');
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════════
    // DATA FETCHING
    // ═══════════════════════════════════════════════════════════════════════════════

    function fetchData() {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'GET',
                url: CONFIG.dataUrl + '?t=' + Date.now(),
                onload: function (response) {
                    if (response.status === 200) {
                        const lines = response.responseText.trim().split('\n');
                        if (lines.length > 1) {
                            const lastLine = lines[lines.length - 1];
                            const parts = lastLine.split(',');
                            if (parts.length >= 3) {
                                resolve({
                                    date: parts[0],
                                    resistance: parseFloat(parts[1]),
                                    support: parseFloat(parts[2])
                                });
                            } else {
                                reject(new Error('Invalid data format'));
                            }
                        } else {
                            reject(new Error('No data'));
                        }
                    } else {
                        reject(new Error('HTTP ' + response.status));
                    }
                },
                onerror: function (error) {
                    reject(error);
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════════════════════════
    // INDICATOR UPDATE
    // ═══════════════════════════════════════════════════════════════════════════════

    async function updateIndicatorSettings(resistance, support) {
        // Find and click on the indicator settings
        const legendItems = document.querySelectorAll('[data-name="legend-source-item"]');

        for (const item of legendItems) {
            const title = item.querySelector('[class*="title"]');
            if (title && title.textContent.toLowerCase().includes('options')) {
                // Found our indicator - click settings
                const settingsBtn = item.querySelector('[data-name="legend-settings-action"]');
                if (settingsBtn) {
                    settingsBtn.click();

                    // Wait for dialog
                    await sleep(600);

                    // Find and update input fields
                    const dialog = document.querySelector('[data-dialog-name="indicator-properties-dialog"]');
                    if (dialog) {
                        const inputs = dialog.querySelectorAll('input[type="text"], input[type="number"]');

                        for (const input of inputs) {
                            const row = input.closest('[class*="cell"]') || input.parentElement;
                            const label = row ? row.textContent.toLowerCase() : '';

                            if (label.includes('resistance') || label.includes('high')) {
                                setInputValue(input, resistance);
                            } else if (label.includes('support') || label.includes('low')) {
                                setInputValue(input, support);
                            }
                        }

                        // Click OK button
                        await sleep(200);
                        const okBtn = dialog.querySelector('[data-name="submit-button"]');
                        if (okBtn) {
                            okBtn.click();
                            return true;
                        }
                    }
                }
            }
        }

        return false;
    }

    function setInputValue(input, value) {
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ═══════════════════════════════════════════════════════════════════════════════
    // MAIN UPDATE LOOP
    // ═══════════════════════════════════════════════════════════════════════════════

    async function fetchAndUpdate() {
        if (state.isUpdating) return;

        state.isUpdating = true;
        setStatus('Updating...');

        try {
            const data = await fetchData();

            // Check if values changed
            if (data.resistance !== state.resistance || data.support !== state.support) {
                state.resistance = data.resistance;
                state.support = data.support;
                state.lastUpdate = new Date();

                updateStatusPanel();

                // Try to update indicator (optional - may not work if indicator not found)
                const updated = await updateIndicatorSettings(data.resistance, data.support);

                if (CONFIG.showNotifications && updated) {
                    GM_notification({
                        title: 'Options Levels Updated',
                        text: `R: $${data.resistance.toLocaleString()} | S: $${data.support.toLocaleString()}`,
                        timeout: 3000
                    });
                }

                console.log('Options Levels updated:', data);
            } else {
                setStatus('No changes');
            }

        } catch (error) {
            console.error('Options Levels error:', error);
            setStatus('Error: ' + error.message, true);
        }

        state.isUpdating = false;
    }

    // ═══════════════════════════════════════════════════════════════════════════════
    // INITIALIZATION
    // ═══════════════════════════════════════════════════════════════════════════════

    function init() {
        console.log('Options Levels Auto-Update v2.0 initialized');

        // Wait for page to settle
        setTimeout(() => {
            createStatusPanel();
            fetchAndUpdate();

            // Set up periodic updates
            setInterval(fetchAndUpdate, CONFIG.updateIntervalMs);
        }, 3000);
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
