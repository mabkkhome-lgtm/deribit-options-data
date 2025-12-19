// ==UserScript==
// @name         TradingView Options Levels Auto-Update
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Automatically updates Options Levels Tracker indicator with latest data from GitHub
// @author       Thales Bot
// @match        https://www.tradingview.com/*
// @match        https://tradingview.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @connect      raw.githubusercontent.com
// @updateURL    https://raw.githubusercontent.com/mabkkhome-lgtm/deribit-options-data/main/tradingview_autoupdate.user.js
// @downloadURL  https://raw.githubusercontent.com/mabkkhome-lgtm/deribit-options-data/main/tradingview_autoupdate.user.js
// ==/UserScript==

(function () {
    'use strict';

    // Configuration
    const CONFIG = {
        csvUrl: 'https://raw.githubusercontent.com/mabkkhome-lgtm/deribit-options-data/main/data/btc_levels.csv',
        updateIntervalMs: 15 * 60 * 1000, // 15 minutes
        indicatorName: 'Options Levels Tracker',
        showNotifications: true,
        autoClickApply: true
    };

    let lastData = '';
    let isUpdating = false;

    // Create status indicator
    function createStatusIndicator() {
        const indicator = document.createElement('div');
        indicator.id = 'options-levels-status';
        indicator.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(26, 26, 46, 0.95);
            color: #fff;
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 12px;
            z-index: 9999;
            border: 1px solid #333;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            cursor: pointer;
            transition: all 0.3s ease;
        `;
        indicator.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span id="status-dot" style="width: 8px; height: 8px; background: #4caf50; border-radius: 50%;"></span>
                <span id="status-text">Options Levels: Active</span>
            </div>
            <div id="status-details" style="font-size: 10px; color: #888; margin-top: 4px;"></div>
        `;
        indicator.onclick = () => fetchAndUpdate();
        document.body.appendChild(indicator);
        return indicator;
    }

    // Update status display
    function updateStatus(text, isError = false) {
        const dot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        const details = document.getElementById('status-details');

        if (dot) dot.style.background = isError ? '#f44336' : '#4caf50';
        if (statusText) statusText.textContent = text;
        if (details) details.textContent = `Last update: ${new Date().toLocaleTimeString()}`;
    }

    // Fetch CSV data from GitHub
    function fetchData() {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'GET',
                url: CONFIG.csvUrl + '?t=' + Date.now(), // Cache bust
                onload: function (response) {
                    if (response.status === 200) {
                        // Remove header line and get data
                        const lines = response.responseText.trim().split('\n');
                        const dataLines = lines.slice(1).join('\n'); // Skip header
                        resolve(dataLines);
                    } else {
                        reject(new Error('Failed to fetch: ' + response.status));
                    }
                },
                onerror: function (error) {
                    reject(error);
                }
            });
        });
    }

    // Find and open indicator settings
    function findIndicatorSettings() {
        // Look for the indicator in the legend
        const legends = document.querySelectorAll('[data-name="legend-source-item"]');

        for (const legend of legends) {
            const titleSpan = legend.querySelector('[class*="title"]');
            if (titleSpan && titleSpan.textContent.includes(CONFIG.indicatorName)) {
                // Found our indicator - click settings icon
                const settingsBtn = legend.querySelector('[data-name="legend-settings-action"]');
                if (settingsBtn) {
                    settingsBtn.click();
                    return true;
                }
            }
        }

        // Alternative: Look in the indicator list
        const indicatorItems = document.querySelectorAll('[class*="legendSourceItem"]');
        for (const item of indicatorItems) {
            if (item.textContent.includes(CONFIG.indicatorName)) {
                const settingsBtn = item.querySelector('[class*="button"]');
                if (settingsBtn) {
                    settingsBtn.click();
                    return true;
                }
            }
        }

        return false;
    }

    // Update the text area input in the indicator settings dialog
    async function updateIndicatorInput(data) {
        // Wait for dialog to open
        await sleep(500);

        // Find the settings dialog
        const dialogs = document.querySelectorAll('[data-dialog-name="indicator-properties-dialog"]');
        let dialog = dialogs[dialogs.length - 1];

        if (!dialog) {
            // Try alternative selector
            dialog = document.querySelector('[class*="dialog-"]');
        }

        if (!dialog) {
            console.log('Options Levels: Dialog not found');
            return false;
        }

        // Find the textarea for data input
        const textareas = dialog.querySelectorAll('textarea');
        let targetTextarea = null;

        for (const ta of textareas) {
            // Check if this is our data textarea (by placeholder or nearby label)
            const parent = ta.closest('[class*="cell"]') || ta.parentElement;
            if (parent && (
                parent.textContent.includes('PASTE DATA') ||
                parent.textContent.includes('data') ||
                ta.placeholder.includes('data')
            )) {
                targetTextarea = ta;
                break;
            }
        }

        // If no labeled textarea found, just use the first one (most likely to be data input)
        if (!targetTextarea && textareas.length > 0) {
            targetTextarea = textareas[0];
        }

        if (targetTextarea) {
            // Clear and set new value
            targetTextarea.value = data;
            targetTextarea.dispatchEvent(new Event('input', { bubbles: true }));
            targetTextarea.dispatchEvent(new Event('change', { bubbles: true }));

            console.log('Options Levels: Data updated in textarea');

            // Click Apply/OK button if configured
            if (CONFIG.autoClickApply) {
                await sleep(300);

                // Find and click the submit/apply button
                const buttons = dialog.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.includes('OK') ||
                        btn.textContent.includes('Apply') ||
                        btn.textContent.includes('Defaults')) {
                        // Skip the "Defaults" button, click OK
                        if (btn.textContent.includes('OK')) {
                            btn.click();
                            console.log('Options Levels: Settings applied');
                            return true;
                        }
                    }
                }

                // Alternative: submit button
                const submitBtn = dialog.querySelector('[data-name="submit-button"]');
                if (submitBtn) {
                    submitBtn.click();
                    return true;
                }
            }

            return true;
        }

        console.log('Options Levels: Textarea not found in dialog');
        return false;
    }

    // Close any open dialog
    function closeDialog() {
        const closeBtn = document.querySelector('[data-name="close"]');
        if (closeBtn) closeBtn.click();
    }

    // Utility: sleep
    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // Main fetch and update function
    async function fetchAndUpdate() {
        if (isUpdating) return;

        isUpdating = true;
        updateStatus('Updating...', false);

        try {
            const data = await fetchData();

            if (data === lastData) {
                updateStatus('Options Levels: No changes', false);
                isUpdating = false;
                return;
            }

            lastData = data;

            // Try to update the indicator
            const foundIndicator = findIndicatorSettings();

            if (foundIndicator) {
                const updated = await updateIndicatorInput(data);

                if (updated) {
                    updateStatus('Options Levels: Updated ✓', false);

                    if (CONFIG.showNotifications) {
                        GM_notification({
                            title: 'Options Levels Updated',
                            text: 'New data loaded: ' + data.split('\n').pop().substring(0, 50),
                            timeout: 3000
                        });
                    }
                } else {
                    updateStatus('Update failed - manual paste needed', true);
                }
            } else {
                updateStatus('Indicator not found on chart', true);
                console.log('Options Levels: Add the "Options Levels Tracker" indicator to your chart first');
            }
        } catch (error) {
            console.error('Options Levels Error:', error);
            updateStatus('Error: ' + error.message, true);
        }

        isUpdating = false;
    }

    // Initialize
    function init() {
        console.log('Options Levels Auto-Update initialized');

        // Wait for page to load
        setTimeout(() => {
            createStatusIndicator();

            // Initial update
            fetchAndUpdate();

            // Set up periodic updates
            setInterval(fetchAndUpdate, CONFIG.updateIntervalMs);

            console.log(`Options Levels: Will update every ${CONFIG.updateIntervalMs / 60000} minutes`);
        }, 3000);
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
