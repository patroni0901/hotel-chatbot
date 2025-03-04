const chatBox = document.getElementById("chatBox");
const conversationList = document.getElementById("conversationList");
const notificationSound = new Audio('/static/notification.mp3');
let socket = null;
let isLoading = false;
let pollingInterval = null;
let isLoggedIn = false;
let lastUpdate = 0;
let currentConvoId = null; // Ensure this starts as null

document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ Page loaded at:", new Date().toLocaleTimeString());
    document.getElementById("loginPage").style.display = "flex";
    document.getElementById("dashboard").style.display = "none";
    checkLogin();
});

async function checkLogin() {
    const agent = localStorage.getItem("agent");
    console.log("🔄 Checking login state at:", new Date().toLocaleTimeString());
    
    if (agent) {
        try {
            console.log("🔄 Verifying session for agent:", agent);
            const response = await fetch("/conversations", { 
                method: "GET",
                credentials: 'include'
            });
            if (response.ok) {
                console.log("✅ Session valid, loading dashboard");
                isLoggedIn = true;
                document.getElementById("loginPage").style.display = "none";
                document.getElementById("dashboard").style.display = "block";
                if (!socket) {
                    console.log("🔌 Initializing WebSocket");
                    listenForNewMessages();
                } else {
                    console.log("🔌 WebSocket already exists");
                }
                loadConversations();
                startPolling();
            } else {
                console.log("❌ Session invalid, clearing agent and showing login");
                localStorage.removeItem("agent");
                showLoginPage();
            }
        } catch (error) {
            console.error("❌ Error verifying session:", error);
            localStorage.removeItem("agent");
            showLoginPage();
        }
    } else {
        console.log("🔒 No agent in localStorage, showing login");
        showLoginPage();
    }
}

function showLoginPage() {
    isLoggedIn = false;
    document.getElementById("loginPage").style.display = "flex";
    document.getElementById("dashboard").style.display = "none";
    if (socket) {
        console.log("🔌 Disconnecting WebSocket");
        socket.disconnect();
        socket = null;
    }
    stopPolling();
    chatBox.innerHTML = "";
    conversationList.innerHTML = "";
    currentConvoId = null; // Reset currentConvoId on logout
}

async function login() {
    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;
    if (!username || !password) {
        alert("Please enter both username and password.");
        return;
    }
    try {
        console.log("🔄 Attempting login...");
        const response = await fetch("/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
            credentials: 'include'
        });
        const data = await response.json();
        if (response.ok) {
            localStorage.setItem("agent", data.agent);
            console.log("✅ Login successful, agent:", data.agent);
            checkLogin();
        } else {
            console.error("❌ Login failed:", data.message);
            alert(data.message || "Login failed.");
        }
    } catch (error) {
        console.error("❌ ERROR: Login failed", error);
        alert("Error connecting to server.");
    }
}

function logout() {
    fetch("/logout", { 
        method: "POST",
        credentials: 'include',
        headers: { "Content-Type": "application/json" }
    })
    .then(response => {
        if (response.ok) {
            console.log("✅ Logout successful");
            localStorage.removeItem("agent");
            showLoginPage();
            window.location.reload();
        } else {
            console.error("❌ Logout failed:", response.status);
            alert("Logout failed, please try again.");
        }
    })
    .catch(error => {
        console.error("Error during logout:", error);
        localStorage.removeItem("agent");
        showLoginPage();
    });
}

async function loadConversations(filter = 'all') {
    if (isLoading) {
        console.log("🔄 Skipping loadConversations, already in progress");
        return;
    }
    isLoading = true;
    try {
        console.log("🔄 Loading conversations with filter:", filter);
        const response = await fetch("/conversations", { credentials: 'include' });
        if (!response.ok) throw new Error("Failed to fetch conversations: " + response.status);
        const conversations = await response.json();
        conversationList.innerHTML = "";
        let unassignedCount = 0, yourCount = 0, teamCount = 0;

        conversations.forEach(convo => {
            const currentAgent = localStorage.getItem("agent");
            if (filter === 'unassigned' && convo.assigned_agent) return;
            if (filter === 'you' && convo.assigned_agent !== currentAgent) return;
            if (filter === 'team' && (!convo.assigned_agent || convo.assigned_agent === currentAgent)) return;

            const convoItem = document.createElement("div");
            convoItem.classList.add("conversation-item");
            const avatar = document.createElement("div");
            avatar.classList.add("conversation-avatar");
            avatar.textContent = convo.username.charAt(0).toUpperCase();
            const details = document.createElement("div");
            details.classList.add("conversation-details");
            const name = document.createElement("div");
            name.classList.add("name");
            name.textContent = `${convo.username} (${convo.channel})` + (convo.assigned_agent ? ` (${convo.assigned_agent})` : '');
            const preview = document.createElement("div");
            preview.classList.add("preview");
            preview.textContent = convo.latest_message || "No messages yet";
            details.appendChild(name);
            details.appendChild(preview);
            convoItem.appendChild(avatar);
            convoItem.appendChild(details);

            // Add "Claim Chat" button for unassigned chats
            if (!convo.assigned_agent) {
                const claimButton = document.createElement("button");
                claimButton.textContent = "Claim Chat";
                claimButton.style.padding = "5px 10px";
                claimButton.style.marginLeft = "10px";
                claimButton.style.backgroundColor = "#007bff";
                claimButton.style.color = "white";
                claimButton.style.border = "none";
                claimButton.style.borderRadius = "5px";
                claimButton.style.cursor = "pointer";
                claimButton.onclick = () => handoff(convo.id);
                convoItem.appendChild(claimButton);
            } else {
                // Allow clicking to load chat if not unassigned
                convoItem.onclick = () => loadChat(convo.id, convo.username);
            }

            conversationList.appendChild(convoItem);

            if (!convo.assigned_agent) unassignedCount++;
            else if (convo.assigned_agent === currentAgent) yourCount++;
            else teamCount++;
        });

        document.getElementById("unassignedCount").textContent = unassignedCount;
        document.getElementById("yourCount").textContent = yourCount;
        document.getElementById("teamCount").textContent = teamCount;
        document.getElementById("allCount").textContent = conversations.length;
        console.log("✅ Conversations loaded, count:", conversations.length);
    } catch (error) {
        console.error("❌ Error loading conversations:", error);
    } finally {
        isLoading = false;
    }
}

async function loadChat(convoId, username) {
    if (isLoading) {
        console.log("🔄 Skipping loadChat, already in progress");
        return;
    }
    isLoading = true;
    try {
        console.log("🔄 Loading chat for convo ID:", convoId);
        // Check visibility before loading the chat
        const isVisible = await checkVisibility(convoId);
        if (!isVisible) {
            console.log(`Conversation ${convoId} is not visible yet, skipping load into Live Conversation`);
            chatBox.innerHTML = "";
            document.getElementById("clientName").textContent = "";
            currentConvoId = null;
            return;
        }
        const response = await fetch(`/messages?conversation_id=${convoId}`, { credentials: 'include' });
        if (!response.ok) throw new Error("Failed to load messages: " + response.status);
        const messages = await response.json();
        chatBox.innerHTML = "";
        messages.forEach(msg => {
            console.log("Message sender:", msg.sender);
            const messageElement = document.createElement("div");
            messageElement.classList.add("message", msg.sender === "user" ? "user-message" : "agent-message");
            messageElement.innerHTML = `<p>${msg.message}</p><span class="message-timestamp">${new Date(msg.timestamp).toLocaleTimeString()}</span>`;
            chatBox.appendChild(messageElement);
        });
        chatBox.scrollTop = chatBox.scrollHeight;
        document.getElementById("clientName").textContent = username;
        currentConvoId = convoId;
        console.log("✅ Chat loaded, message count:", messages.length);
    } catch (error) {
        console.error("❌ Error loading chat:", error);
    } finally {
        isLoading = false;
    }
}

async function isAuthenticated() {
    try {
        const response = await fetch("/check-auth", { credentials: 'include' });
        const data = await response.json();
        return data.is_authenticated;
    } catch (error) {
        console.error("❌ Error checking auth:", error);
        return false;
    }
}

async function sendMessage() {
    const messageInput = document.getElementById("messageInput");
    const message = messageInput.value.trim();
    if (!message || !currentConvoId) {
        console.log("⚠️ No message or convo ID, skipping send");
        return;
    }
    messageInput.value = "";
    
    const isAgent = await isAuthenticated();
    const sender = isAgent ? "agent" : "user";
    console.log("🔄 Sending message as:", sender);

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: currentConvoId, message }),
            credentials: 'include'
        });
        const data = await response.json();
        console.log("Response from /chat:", data);
        if (sender !== "agent" && data.reply) {
            addMessage(data.reply, "ai");
        }
    } catch (error) {
        console.error("❌ Error sending message:", error);
    }
}

function addMessage(content, sender) {
    const messageElement = document.createElement("div");
    messageElement.classList.add("message", sender === "user" ? "user-message" : "agent-message");
    messageElement.innerHTML = `<p>${content}</p><span class="message-timestamp">${new Date().toLocaleTimeString()}</span>`;
    chatBox.appendChild(messageElement);
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function checkVisibility(convoId) {
    try {
        const response = await fetch(`/check-visibility?conversation_id=${convoId}`, { credentials: 'include' });
        const data = await response.json();
        console.log(`Visibility check for convo ID ${convoId}:`, data.visible);
        return data.visible;
    } catch (error) {
        console.error("❌ Error checking visibility:", error);
        return false;
    }
}

function listenForNewMessages() {
    if (socket) {
        console.log("🔄 WebSocket already connected, skipping");
        return;
    }
    socket = io('https://hotel-chatbot-1qj5.onrender.com', { 
        transports: ["websocket"],
        reconnection: false
    });
    socket.on("connect", () => {
        console.log("✅ WebSocket connected at:", new Date().toLocaleTimeString());
    });
    socket.on("connect_error", (error) => {
        console.error("❌ WebSocket connection error:", error);
    });
    socket.on("new_message", async (data) => {
        console.log("📩 New message received:", data);
        console.log("Current convoId:", currentConvoId, "Data convo_id:", data.convo_id);
        
        // Check if the conversation is visible before displaying in Live Conversation panel
        const isVisible = await checkVisibility(data.convo_id);
        if (isVisible) {
            if (data.convo_id === currentConvoId) {
                console.log("Adding message to current conversation:", data.message);
                addMessage(data.message, data.sender);
            } else {
                console.log("Loading chat into Live Conversation:", data.convo_id);
                loadChat(data.convo_id, data.user || "Unknown");
            }
        } else {
            console.log(`Conversation ${data.convo_id} is not visible yet, skipping display in Live Conversation`);
        }

        const now = Date.now();
        if (now - lastUpdate > 2000) {
            loadConversations();
            lastUpdate = now;
        }
    });
    socket.on("handoff", (data) => {
        console.log("🔔 Handoff event:", data);
        alert(`New unassigned chat with ${data.user} (ID: ${data.conversation_id})`);
        loadConversations();
    });
}

const messageInput = document.getElementById("messageInput");
messageInput.removeEventListener("keypress", handleKeypress);
messageInput.addEventListener("keypress", handleKeypress);
function handleKeypress(event) {
    if (event.key === "Enter") sendMessage();
}

async function handoff(convoId) {
    try {
        console.log("🔄 Attempting handoff for convo ID:", convoId);
        const response = await fetch("/handoff", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: convoId }),
            credentials: 'include'
        });
        const data = await response.json();
        alert(data.message);
        loadConversations();
        console.log("✅ Handoff successful");
    } catch (error) {
        console.error("❌ Error during handoff:", error);
        alert("Failed to assign chat.");
    }
}

function filterByChannel(channel) {
    console.log(`Filtering by ${channel} - not implemented yet`);
}

function startPolling() {
    if (pollingInterval) {
        console.log("🔄 Polling already active");
        return;
    }
    pollingInterval = setInterval(() => {
        if (!isLoading && isLoggedIn) {
            const now = Date.now();
            if (now - lastUpdate > 10000) {
                console.log("🔄 Polling conversations");
                loadConversations();
                lastUpdate = now;
            }
        }
    }, 10000);
}

function stopPolling() {
    if (pollingInterval) {
        console.log("🔄 Stopping polling");
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}
