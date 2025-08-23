document.addEventListener('DOMContentLoaded', () => {
    const commandForm = document.getElementById('command-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const toolHistory = document.getElementById('history-content');
    const recordButton = document.getElementById('record-btn');

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.lang = 'en-US';
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        recordButton.addEventListener('click', () => {
            if (recordButton.classList.contains('recording')) {
                recognition.stop();
            } else {
                recognition.start();
            }
        });

        recognition.onstart = () => {
            recordButton.classList.add('recording');
            recordButton.textContent = '🛑';
        };

        recognition.onend = () => {
            recordButton.classList.remove('recording');
            recordButton.textContent = '🎤';
        };

        recognition.onresult = (event) => {
            let final_transcript = '';
            for (let i = 0; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    final_transcript += event.results[i][0].transcript;
                }
            }
            userInput.value = final_transcript;
        };

        recognition.onerror = (event) => {
            console.error("Speech recognition error", event.error);
            alert(`Error during speech recognition: ${event.error}`);
        };

    } else {
        recordButton.style.display = 'none';
        console.log("Speech recognition not supported in this browser.");
    }

    // Handle textarea auto-resize
    function autoResize() {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
    }

    userInput.addEventListener('input', autoResize);

    // Handle Enter vs Shift+Enter
    userInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            commandForm.dispatchEvent(new Event('submit'));
        }
    });

    commandForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const command = userInput.value.trim();
        if (!command) return;
        userInput.value = '';
        autoResize(); // Reset height after clearing
        await sendCommand(command);
    });

    async function sendCommand(command) {
        appendMessage(command, 'user-message');
        const loadingMessage = appendMessage('Thinking...', 'bot-message loading');
        chatBox.scrollTop = chatBox.scrollHeight;

        try {
            const response = await fetch('/command', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ input: command }),
            });

            const data = await response.json();
            loadingMessage.remove();
            handleBotResponse(data);

        } catch (error) {
            console.error('Error:', error);
            loadingMessage.remove();
            appendMessage('Sorry, something went wrong. Please check the server logs.', 'bot-message');
        }
    }

    function appendMessage(content, className) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', ...className.split(' '));
        messageDiv.innerHTML = content;
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
        return messageDiv;
    }

    function handleBotResponse(data) {
        let content = '';
        let rawText = '';
        if (data.error) {
            content = `<strong>Error:</strong> ${data.error}`;
            rawText = data.error;
        } 
        else if (data.response) {
            rawText = data.response;
            content = marked.parse(data.response);
            if (data.raw_json) {
                const toolName = data.tool_used || 'Tool Output';
                let jsonContent = data.raw_json;
                try {
                    jsonContent = JSON.stringify(JSON.parse(data.raw_json), null, 2);
                } catch (e) {
                    jsonContent = "Invalid JSON format";
                }
                content += `<br><br><details class="tool-output"><summary>${toolName} (raw JSON)</summary><pre>${jsonContent}</pre></details>`;
                updateToolHistory(data);
            }
        } else {
            content = formatStructuredData(data);
            updateToolHistory(data);
        }
        appendMessage(content, 'bot-message');
    }

    function updateToolHistory(data) {
        const historyEntry = document.createElement('div');
        historyEntry.classList.add('history-entry');

        if (!data.tool_used) return;
        
        const toolName = data.tool_used;
        const toolInput = data.tool_input ? JSON.stringify(data.tool_input, null, 2) : 'No input';
        let toolOutput = data.raw_json; // Already a stringified JSON
        try {
            toolOutput = JSON.stringify(JSON.parse(toolOutput), null, 2);
        } catch(e) {
            toolOutput = "Invalid JSON format";
        }

        let entryContent = `<h4>${toolName}</h4>`;
        entryContent += `<details><summary>Input</summary><pre>${toolInput}</pre></details>`;
        entryContent += `<details><summary>Output</summary><pre>${toolOutput}</pre></details>`;
        entryContent += `<p><small>Time: ${new Date().toLocaleString()}</small></p>`;
        entryContent += `<br><hr><br>`;

        historyEntry.innerHTML = entryContent;
        toolHistory.prepend(historyEntry); // Prepend to show the latest first
    }

    function formatStructuredData(data) {
        if (data.title && data.commands) {
            let html = `<h3>${data.title}</h3>`;
            for (const [category, commands] of Object.entries(data.commands)) {
                html += `<h4>${category}</h4><ul>`;
                commands.forEach(cmd => {
                    html += `<li><code>${cmd.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></li>`;
                });
                html += `</ul>`;
            }
            return html;
        }
        return `<pre style="white-space: pre-wrap; word-wrap: break-word; max-width: 100%; overflow-wrap: break-word;">${JSON.stringify(data, null, 2)}</pre>`;
    }
});