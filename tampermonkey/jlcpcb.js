// ==UserScript==
// @name         Highlight Layers Label
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Changes the background of the "Layers" label to pink
// @author       You
// @match        https://cart.jlcpcb.com/quote*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    function getDirectTextContent(element) {
        let directText = '';
        element.childNodes.forEach(node => {
            if (node.nodeType === Node.TEXT_NODE) {
                directText += node.textContent.trim();
            }
        });
        return directText;
    }

    function findLabelByText(text) {
        const labels = document.querySelectorAll('label');
        for (const label of labels) {
            if (getDirectTextContent(label) === text) {
                return label;
            }
        }
        return null;
    }

    function specHighlightAndNote(labelText) {
        return function(key, value) {
            const label = findLabelByText(labelText);
            if (!label) {
                console.warn('Label not found for:', labelText);
                return;
            }
            label.style.backgroundColor = 'pink';
            label.style.padding = '0.5em';
            label.style.borderRadius = '0.5em';

            // Check if there is a child element with class 'specfiledesc'
            let specFile = label.querySelector('.specfile');
            if (!specFile) {
                specFile = document.createElement('span');
                specFile.classList.add('specfile');
                specFile.style.fontWeight = 'bold';
                specFile.style.color = 'blue';
                specFile.style.marginLeft = '0.5em';
                label.appendChild(specFile);
            }

            // Update the content
            specFile.textContent = value;
            specFile.textContent = ` (${value})`;
            // Set title attribute to show the full content on hover
            specFile.title = value;
        }
    }

    const specHandlers = {
        'thickness': specHighlightAndNote('PCB Thickness'),
        'surface_finish': specHighlightAndNote('Surface Finish'),
        'mark_on_pcb': specHighlightAndNote('Mark on PCB'),
        'impedance_control': specHighlightAndNote('Impedance Control'),
    };

    const defaultSpec = {
        'mark_on_pcb': '2D'
    };

    function handleJlcSpec(spec) {
        for (const [key, value] of Object.entries(spec)) {
            const handler = specHandlers[key];
            if (handler) {
                handler(key, value);
            } else {
                console.warn('No handler for key:', key);
            }
        }
    }

    setInterval(() => {
        // Ugly hack, but some of the options only appear after the Gerber is
        // processed...
        if (window._jlcpcbSpec) {
            handleJlcSpec(window._jlcpcbSpec);
        }
    }, 1000);

    async function handleGerberFile(file) {
        try {
            // Ensure JSZip is loaded
            if (typeof JSZip === 'undefined') {
                console.error('JSZip library not loaded.');
                return;
            }

            console.log('Processing Gerber file:', file.name);

            const zip = new JSZip();
            const zipContent = await zip.loadAsync(file); // Unzip the file

            console.log('ZIP contents:', Object.keys(zipContent.files)); // Log all files for debugging

            // Look for jlcpcb.json inside the zip
            const jlcpcbJsonFile = zipContent.file('gerber/jlcpcb.json');

            if (!jlcpcbJsonFile) {
                console.warn('jlcpcb.json not found in the zip file.');
                return;
            }

            // Extract and parse the JSON file
            const jsonContent = await jlcpcbJsonFile.async('string');
            const parsedContent = JSON.parse(jsonContent);

            console.log('Parsed jlcpcb.json contents:', parsedContent);

            // Merge defaultSpec
            for (const [key, value] of Object.entries(defaultSpec)) {
                if (!parsedContent[key]) {
                    parsedContent[key] = value;
                }
            }

            // Pass the parsed content to handleJlcSpec
            window._jlcpcbSpec = parsedContent;
            // Handle after the Gerber is processed
            //handleJlcSpec(parsedContent);
        } catch (error) {
            console.error('Error processing Gerber file:', error);
        }
    }

    function extractGerberFile(formData) {
        for (const entry of formData.entries()) {
            const [key, value] = entry;
            if (key === 'gerberFile') {
                handleGerberFile(value);
            }
        }
    }

    (function() {
        // Load the JSZip library
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
        document.head.appendChild(script);
    })();

    // Override XMLHttpRequest to intercept POST requests
    (function() {
        const originalXHR = window.XMLHttpRequest;

        function CustomXHR() {
            const xhr = new originalXHR();
            let sendData = null;

            // Override the open method to monitor requests to the desired URL
            const originalOpen = xhr.open;
            xhr.open = function(method, url, ...args) {
                this._isTargetRequest = method.toUpperCase() === 'POST' &&
                    url.includes('/api/overseas-shop-cart/v1/file/uploadGerber');
                return originalOpen.apply(this, [method, url, ...args]);
            };

            // Override the send method to extract form data
            const originalSend = xhr.send;
            xhr.send = function(data) {
                if (this._isTargetRequest && data instanceof FormData) {
                    console.log('Intercepted POST request to uploadGerber');
                    extractGerberFile(data);
                }
                return originalSend.apply(this, [data]);
            };

            return xhr;
        }

        // Replace the global XMLHttpRequest with the custom one
        window.XMLHttpRequest = CustomXHR;
    })();

    // Override fetch to intercept requests as well
    (function() {
        const originalFetch = window.fetch;

        window.fetch = function(resource, options = {}) {
            const url = typeof resource === 'string' ? resource : resource.url;
            if (options.method === 'POST' && url.includes('/api/overseas-shop-cart/v1/file/uploadGerber')) {
                console.log('Intercepted fetch POST request to uploadGerber');
                if (options.body instanceof FormData) {
                    extractGerberFile(options.body);
                }
            }
            return originalFetch.apply(this, [resource, options]);
        };
    })();
})();
