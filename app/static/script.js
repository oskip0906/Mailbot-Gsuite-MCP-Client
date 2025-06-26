document.addEventListener('DOMContentLoaded', () => {
    const commandForm = document.getElementById('command-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');

    commandForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const command = userInput.value.trim();
        if (!command) return;
        userInput.value = '';
        await sendCommand(command);
    });

    async function sendCommand(command) {
        appendMessage(command, 'user-message');
        const loadingMessage = appendMessage('Thinking', 'bot-message loading');
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
        if (data.error) {
            content = `<strong>Error:</strong> ${data.error}`;
        } else if (data.response) {
            content = data.response.replace(/\n/g, '<br>');
        } else {
            content = formatStructuredData(data);
        }
        appendMessage(content, 'bot-message');
    }

    function formatStructuredData(data) {
        if (data.title && data.commands) { // For 'help' command
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
        // For 'list', 'inspect', or other JSON responses
        return `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    }
});