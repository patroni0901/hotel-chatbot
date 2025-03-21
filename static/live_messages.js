console.log('live_messages.js loaded successfully');

// Define Socket.IO instance
const socket = io('https://hotel-chatbot-1qj5.onrender.com', {
    transports: ["websocket", "polling"],
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000
});

// Global variables
let currentConversationId = null;
let currentAgent = null;
let lastMessageDate = null;
let isConnected = false;

// Toast notification function
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        console.error('Toast container not found.');
        return;
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.textContent = message;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('show');
    }, 100);

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3000);
}

// Format timestamp for display
function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
        return 'Invalid Time';
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Format date for message separators
function formatDateForSeparator(timestamp) {
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
        return 'Unknown Date';
    }
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
        return 'Today';
    }
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
        return 'Yesterday';
    }
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

// Add date separator to chat
function addDateSeparator(dateStr) {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) {
        console.error('Chat box not found.');
        return;
    }
    const separator = document.createElement('div');
    separator.className = 'date-separator';
    separator.textContent = dateStr;
    chatBox.appendChild(separator);
}

function appendMessage(msg, sender) {
    console.log('Appending message:', msg, 'Sender:', sender);
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) {
        console.error('Chat box not found.');
        return;
    }

    // Validate message properties
    if (!msg || typeof msg.message !== 'string') {
        console.error('Invalid message object:', msg);
        return;
    }

    const timestamp = msg.timestamp || new Date().toISOString();
    const messageDate = new Date(timestamp);
    if (isNaN(messageDate.getTime())) {
        console.error('Invalid timestamp in message:', msg);
        return;
    }

    const dateStr = formatDateForSeparator(timestamp);
    if (!lastMessageDate || formatDateForSeparator(lastMessageDate) !== dateStr) {
        addDateSeparator(dateStr);
        lastMessageDate = messageDate;
    }

    const div = document.createElement('div');
    const isUser = sender === 'user';
    const isAgent = sender === 'agent';
    div.className = 'message';
    div.classList.add(isUser ? 'user-message' : isAgent ? 'agent-message' : 'ai-message');

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = msg.message;
    div.appendChild(bubble);

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const time = formatTimestamp(timestamp);
    meta.innerHTML = `${time}${isAgent ? '<span class="checkmark">✓✓</span>' : ''}`;
    div.appendChild(meta);

    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Send a message from the agent
async function sendMessage() {
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    if (!messageInput || !sendButton) {
        console.error('Message input or send button not found.');
        showToast('Message input or send button not found.', 'error');
        return;
    }

    const message = messageInput.value.trim();
    if (!message) {
        return;
    }

    if (!currentConversationId) {
        showToast('No conversation selected.', 'error');
        return;
    }

    try {
        const response = await fetch('/live-messages/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversation_id: currentConversationId,
                message: message,
                sender: 'agent'
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error(data.error || 'Unknown error');
        }

        // Clear the input and disable the send button
        messageInput.value = '';
        sendButton.disabled = true;

        // Append the message to the chat box
        appendMessage({ message, timestamp: new Date().toISOString() }, 'agent');

        // Update the conversation list
        fetchConversations();
    } catch (error) {
        console.error('Error sending message:', error);
        showToast(`Failed to send message: ${error.message}`, 'error');
    }
}

// Check authentication status on page load
document.addEventListener('DOMContentLoaded', () => {
    const loginPage = document.getElementById('loginPage');
    const dashboardSection = document.getElementById('dashboard');
    if (!loginPage || !dashboardSection) {
        console.error('Required DOM elements (loginPage, dashboard) are missing.');
        return;
    }

    checkAuthStatus();
    fetchSettings();

    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    if (messageInput && sendButton) {
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' || e.keyCode === 13) {
                e.preventDefault();
                sendMessage();
            }
        });
        messageInput.addEventListener('input', () => {
            sendButton.disabled = !messageInput.value.trim();
            if (messageInput.value.trim() && currentConversationId) {
                socket.emit('typing', { conversation_id: currentConversationId, agent: currentAgent });
            }
        });
        sendButton.addEventListener('click', sendMessage);
    } else {
        console.error('Message input or send button not found.');
    }

    const attachIcon = document.getElementById('attach-icon');
    if (attachIcon) {
        attachIcon.addEventListener('click', () => {
            showToast('File attachment is not yet implemented', 'info');
        });
    }

    const aiToggle = document.getElementById('ai-toggle');
    const aiToggleError = document.getElementById('ai-toggle-error');
    if (aiToggle && aiToggleError) {
        aiToggle.addEventListener('change', async (e) => {
            const aiEnabled = e.target.checked ? '1' : '0';
            try {
                const response = await fetch('/live-messages/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ai_enabled: aiEnabled })
                });
                if (!response.ok) {
                    throw new Error(`Failed to update AI settings: ${response.status}`);
                }
                const data = await response.json();
                if (data.status !== 'success') {
                    throw new Error(data.error || 'Unknown error');
                }
                showToast(`AI has been ${aiEnabled === '1' ? 'enabled' : 'disabled'}`, 'success');
                aiToggleError.style.display = 'none';
            } catch (error) {
                console.error('Error updating AI settings:', error);
                e.target.checked = !e.target.checked;
                aiToggleError.textContent = 'Error updating AI settings: ' + error.message;
                aiToggleError.style.display = 'inline';
                showToast(`Error updating AI settings: ${error.message}`, 'error');
            }
        });
    } else {
        console.error('AI toggle or error element not found.');
    }

    const logoutButton = document.getElementById('logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            fetch('/logout', {
                method: 'POST',
            })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! Status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.message === 'Logged out successfully') {
                        currentAgent = null;
                        loginPage.style.display = 'flex';
                        dashboardSection.style.display = 'none';
                    }
                })
                .catch(error => {
                    console.error('Error during logout:', error);
                    showToast('Error during logout: ' + error.message, 'error');
                });
        });
    } else {
        console.error('Logout button not found.');
    }
});

// Fetch AI settings
async function fetchSettings() {
    try {
        const response = await fetch('/live-messages/settings');
        if (!response.ok) {
            throw new Error(`Failed to fetch settings: ${response.status}`);
        }
        const settings = await response.json();
        const aiToggle = document.getElementById('ai-toggle');
        const aiToggleError = document.getElementById('ai-toggle-error');
        if (aiToggle && aiToggleError) {
            aiToggle.checked = settings.ai_enabled === '1';
            aiToggleError.style.display = 'none';
        } else {
            console.error('AI toggle or error element not found during fetchSettings.');
        }
    } catch (error) {
        console.error('Error fetching settings:', error);
        const aiToggleError = document.getElementById('ai-toggle-error');
        if (aiToggleError) {
            aiToggleError.textContent = 'Failed to load AI setting: ' + error.message;
            aiToggleError.style.display = 'inline';
        }
        showToast('Error fetching settings: ' + error.message, 'error');
    }
}

// Check if user is authenticated
function checkAuthStatus() {
    fetch('/check-auth')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            const loginPage = document.getElementById('loginPage');
            const dashboardSection = document.getElementById('dashboard');
            if (data.is_authenticated) {
                currentAgent = data.agent;
                console.log("Current Agent:", currentAgent);
                loginPage.style.display = 'none';
                dashboardSection.style.display = 'flex';
                fetchConversations();
            } else {
                loginPage.style.display = 'flex';
                dashboardSection.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Error checking auth status:', error);
            showToast('Error checking auth status: ' + error.message, 'error');
        });
}

// Login function for the button
function login() {
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    if (!usernameInput || !passwordInput) {
        console.error('Username or password input missing.');
        showToast('Username or password input missing.', 'error');
        return;
    }

    const username = usernameInput.value;
    const password = passwordInput.value;

    fetch('/login', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.message === 'Login successful') {
                currentAgent = data.agent;
                console.log("Current Agent:", currentAgent);
                document.getElementById('loginPage').style.display = 'none';
                document.getElementById('dashboard').style.display = 'flex';
                fetchConversations();
            } else {
                showToast('Login failed: ' + data.message, 'error');
            }
        })
        .catch(error => {
            console.error('Error during login:', error);
            showToast('Error during login: ' + error.message, 'error');
        });
}

// Fetch conversations
async function fetchConversations() {
    const convoLoadingSpinner = document.getElementById('convo-loading-spinner');
    if (!convoLoadingSpinner) {
        console.error('Conversation loading spinner not found.');
        return;
    }
    convoLoadingSpinner.style.display = 'block';
    try {
        const response = await fetch('/live-messages/all-whatsapp-messages');
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }
        const data = await response.json();
        console.log('Fetched conversations:', data); // Debugging log

        const conversationList = document.getElementById('conversation-list');
        if (!conversationList) {
            console.error('Conversation list not found.');
            return;
        }
        conversationList.innerHTML = '';

        // Handle both { conversations: [...] } and flat [...] response structures
        const conversations = Array.isArray(data) ? data : data.conversations || [];
        if (conversations.length === 0) {
            console.warn('No conversations found.');
            const emptyMessage = document.createElement('div');
            emptyMessage.className = 'empty-conversations';
            emptyMessage.textContent = 'No conversations available.';
            emptyMessage.style.textAlign = 'center';
            emptyMessage.style.color = '#666';
            emptyMessage.style.padding = '20px';
            conversationList.appendChild(emptyMessage);
            return;
        }

        conversations.forEach(convo => {
            const convoItem = document.createElement('div');
            convoItem.classList.add('conversation-item');
            if (currentConversationId === convo.conversation_id) { // Use conversation_id instead of convo_id
                convoItem.classList.add('active');
            }

            // Determine the last message
            let lastMessage = 'No messages';
            if (convo.last_message) {
                lastMessage = convo.last_message;
            } else if (convo.messages && Array.isArray(convo.messages) && convo.messages.length > 0) {
                lastMessage = convo.messages[convo.messages.length - 1].message;
            }

            convoItem.innerHTML = `
                <div class="avatar"></div>
                <div class="info">
                    <div class="name">${convo.username || convo.conversation_id}</div>
                    <div class="last-message">${lastMessage}</div>
                </div>
            `;
            convoItem.addEventListener('click', () => loadConversation(convo.conversation_id, convo.username || convo.conversation_id));
            conversationList.appendChild(convoItem);
        });
    } catch (error) {
        console.error('Error fetching conversations:', error);
        showToast('Error fetching conversations: ' + error.message, 'error');
    } finally {
        convoLoadingSpinner.style.display = 'none';
    }
}

// Declare lastMessageDate globally

async function loadConversation(convoId, username) {
    if (currentConversationId) {
        socket.emit('leave_conversation', { conversation_id: currentConversationId });
    }
    currentConversationId = convoId;
    socket.emit('join_conversation', { conversation_id: convoId });

    const chatHeader = document.getElementById('chat-header');
    const inputContainer = document.getElementById('input-container');
    const chatTitle = document.getElementById('chat-title');
    if (chatHeader && inputContainer && chatTitle) {
        chatHeader.style.display = 'flex';
        inputContainer.style.display = 'flex';
        chatTitle.textContent = username;
    } else {
        console.error('Chat header, input container, or chat title not found.');
        return;
    }

    const conversationItems = document.querySelectorAll('.conversation-item');
    conversationItems.forEach(item => item.classList.remove('active'));
    const selectedItem = Array.from(conversationItems).find(item => item.textContent.includes(username));
    if (selectedItem) {
        selectedItem.classList.add('active');
    }

    const chatLoadingSpinner = document.getElementById('chat-loading-spinner');
    if (chatLoadingSpinner) {
        chatLoadingSpinner.style.display = 'block';
    } else {
        console.warn('Chat loading spinner not found. Proceeding without spinner.');
    }

    try {
        // Fetch messages for the given conversation ID
        const response = await fetch(`/live-messages/messages?conversation_id=${convoId}`);
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}, Status Text: ${response.statusText}`);
        }

        // Parse the response as JSON
        const data = await response.json();
        console.log('Fetched messages for conversation ID', convoId, ':', data); // Debugging log

        // Handle both flat [...] and { messages: [...] } response structures
        const messages = Array.isArray(data) ? data : data.messages || [];

        // Validate the response data
        if (!Array.isArray(messages)) {
            throw new Error('Invalid response: messages is not an array');
        }

        // Get the chat box element
        const chatBox = document.getElementById('chat-box');
        if (!chatBox) {
            throw new Error('Chat box element not found in the DOM');
        }

        // Clear the chat box and reset the last message date
        chatBox.innerHTML = '';
        lastMessageDate = null;

        // Display a message if the conversation is empty
        if (messages.length === 0) {
            const emptyMessage = document.createElement('div');
            emptyMessage.className = 'empty-conversation';
            emptyMessage.textContent = 'No messages in this conversation yet.';
            emptyMessage.style.textAlign = 'center';
            emptyMessage.style.color = '#666';
            emptyMessage.style.padding = '20px';
            chatBox.appendChild(emptyMessage);
        } else {
            // Append each message to the chat box
            messages.forEach((msg, index) => {
                try {
                    appendMessage(msg, msg.sender);
                } catch (appendError) {
                    console.error(`Error appending message at index ${index}:`, appendError, msg);
                }
            });
        }

        // Scroll to the bottom of the chat box
        chatBox.scrollTop = chatBox.scrollHeight;
    } catch (error) {
        console.error('Error loading messages for conversation ID', convoId, ':', error);
        showToast(`Failed to load messages: ${error.message}`, 'error');
    } finally {
        if (chatLoadingSpinner) {
            chatLoadingSpinner.style.display = 'none';
        }
    }
}

// Socket.IO event listeners
socket.on('connect', () => {
    isConnected = true;
    showToast('Connected to server', 'success');
});

socket.on('disconnect', () => {
    isConnected = false;
    showToast('Disconnected from server', 'error');
});

socket.on('live_message', (data) => {
    if (data.convo_id === currentConversationId) {
        appendMessage({ message: data.message, timestamp: new Date().toISOString() }, data.sender);
    }
    const conversationList = document.getElementById('conversation-list');
    if (!conversationList) {
        console.error('Conversation list not found.');
        return;
    }
    const convoItem = Array.from(conversationList.children).find(item => item.textContent.includes(data.username));
    if (convoItem) {
        convoItem.querySelector('.last-message').textContent = data.message;
    }
});

socket.on('typing', (data) => {
    if (data.conversation_id === currentConversationId && data.agent !== currentAgent) {
        const chatBox = document.getElementById('chat-box');
        if (!chatBox) {
            console.error('Chat box not found.');
            return;
        }
        let typingIndicator = chatBox.querySelector('.typing-indicator');
        if (!typingIndicator) {
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = '<div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
            chatBox.appendChild(typingIndicator);
        }
        typingIndicator.style.display = 'block';
        setTimeout(() => {
            typingIndicator.style.display = 'none';
        }, 3000);
    }
});

socket.on('error', (data) => {
    showToast(data.message, 'error');
});

socket.on('refresh_conversations', () => {
    fetchConversations();
});

socket.on('settings_updated', (settings) => {
    if ('ai_enabled' in settings) {
        const aiToggle = document.getElementById('ai-toggle');
        const aiToggleError = document.getElementById('ai-toggle-error');
        if (aiToggle && aiToggleError) {
            aiToggle.checked = settings.ai_enabled === '1';
            aiToggleError.style.display = 'none';
            showToast(`AI has been ${settings.ai_enabled === '1' ? 'enabled' : 'disabled'}`, 'success');
        } else {
            console.error('AI toggle or error element not found during settings update.');
        }
    }
});

socket.on("reconnect", (attempt) => {
    fetchConversations();
    fetchSettings();
    if (currentConversationId) {
        socket.emit('join_conversation', { conversation_id: currentConversationId });
    }
    showToast('Reconnected to server', 'success');
});

socket.on("reconnect_error", (error) => {
    showToast('Failed to reconnect to server', 'error');
});
