// =========================
// 🔍 SIDEBAR USER SEARCH/FILTER (moved from template)
// =========================
document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("search-input");
    const userListContainer = document.getElementById("user-list-container");
    if (!searchInput || !userListContainer) return;

    // Build user list from DOM (for initial render)
    allUsers = Array.from(userListContainer.querySelectorAll(".user-item")).map(item => {
        return {
            id: item.getAttribute("data-user-id"),
            name: item.querySelector(".font-medium")?.innerText || "",
            nameLower: (item.querySelector(".font-medium")?.innerText || "").toLowerCase(),
            last_message: item.querySelector(".text-xs.text-gray-400")?.innerText || "",
            unread_count: item.querySelector(".bg-green-500")?.innerText || 0,
            is_online: item.querySelector(".user-status")?.classList.contains("text-green-400"),
            has_chat: item.getAttribute("data-has-chat") === "true",
            avatar_url: item.getAttribute("data-avatar-url") || ""
        };
    });

    renderUserList = function(filter) {
        let html = "";
        let chatUsers = allUsers.filter(u => u.has_chat);
        let ids = new Set();
        // Always show all chat users
        chatUsers.forEach(u => {
            html += userHtml(u);
            ids.add(u.id);
        });
        // If searching, add non-chat users matching search
        if (filter) {
            let searchUsers = allUsers.filter(u => u.nameLower.startsWith(filter) && !u.has_chat);
            searchUsers.forEach(u => {
                if (!ids.has(u.id)) {
                    html += userHtml(u);
                }
            });
        }
        userListContainer.innerHTML = html;
    }

    function userHtml(u) {
        const activeUserId = new URLSearchParams(window.location.search).get('user');
        return `<a href="/dashboard/?user=${u.id}">
            <div class="user-item flex justify-between items-center px-4 py-3 hover:bg-gray-800 cursor-pointer transition${(String(activeUserId) === String(u.id)) ? ' bg-gray-800' : ''}" data-name="${u.nameLower}" data-user-id="${u.id}" data-has-chat="${u.has_chat}" data-avatar-url="${u.avatar_url || ''}">
                <div class="flex items-center gap-3">
                    <img src="${u.avatar_url || 'https://i.pravatar.cc/35?u=' + encodeURIComponent(u.id)}" class="rounded-full h-9 w-9 object-cover">
                    <div>
                        <p class="font-medium">${u.name}</p>
                        <p class="text-xs text-gray-400 truncate w-32">${u.last_message}</p>
                    </div>
                </div>
                <div class="flex flex-col items-end gap-1">
                    ${u.unread_count > 0 ? `<span class="bg-green-500 text-xs px-2 py-0.5 rounded-full">${u.unread_count}</span>` : ''}
                    <span class="user-status text-xs ${u.is_online ? 'text-green-400' : 'text-gray-500'}">● ${u.is_online ? 'online' : 'offline'}</span>
                </div>
            </div>
        </a>`;
    }

    searchInput.addEventListener("keyup", function () {
        let value = this.value.toLowerCase().trim();
        renderUserList(value);
    });

    // Initial render: only chat users
    renderUserList("");
});
// =========================
// 🔥 FILE PREVIEW (overlay above input, with X button)
// =========================
document.addEventListener("DOMContentLoaded", function () {
    let fileInput = document.getElementById("file-input");
    let preview = document.getElementById("file-preview");
    if (!fileInput || !preview) return;
    fileInput.addEventListener("change", function () {
        preview.innerHTML = "";
        let file = fileInput.files[0];
        if (!file) {
            preview.classList.add("hidden");
            return;
        }
        let ext = file.name.split('.').pop().toLowerCase();
        let url = URL.createObjectURL(file);
        let content = "";
        if (["jpg","jpeg","png","gif","webp","bmp","svg"].includes(ext)) {
            content = `<img src="${url}" alt="preview" class="max-w-xs max-h-40 rounded" />`;
        } else if (["mp3","wav","ogg","aac","m4a"].includes(ext)) {
            content = `<audio controls src="${url}"></audio>`;
        } else if (["mp4","avi","mov","wmv","flv","mkv","webm"].includes(ext)) {
            content = `<video controls src="${url}" class="max-w-xs max-h-40"></video>`;
        } else {
            content = `<span class=\"text-gray-700\">${file.name}</span>`;
        }
        // Add X button
        content += `<button id="remove-preview-btn" class="ml-2 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center absolute top-2 right-2 shadow-lg" title="Remove file">&times;</button>`;
        preview.innerHTML = `<div class=\"relative bg-white border rounded shadow-lg p-3 flex items-center\">${content}</div>`;
        preview.classList.remove("hidden");
        // Remove preview on X click
        document.getElementById("remove-preview-btn").onclick = function() {
            preview.innerHTML = "";
            preview.classList.add("hidden");
            fileInput.value = "";
        };
    });
});
// =========================
// 🔥 GLOBAL
// =========================
let socket = null;
let currentUserId = null;
let allUsers = [];
let renderUserList = function () {};
let isBlockedByCurrentUser = false;
let isReportedByChatUser = false;

function setComposerDisabled(disabled, reasonMessage = "") {
    const input = document.getElementById("message-input");
    const sendButton = document.getElementById("send-button");
    const form = document.getElementById("composer-form");
    const banner = document.getElementById("report-block-banner");

    if (input) input.disabled = !!disabled;
    if (sendButton) {
        sendButton.disabled = !!disabled;
        sendButton.classList.toggle("opacity-60", !!disabled);
        sendButton.classList.toggle("cursor-not-allowed", !!disabled);
    }
    if (form) form.classList.toggle("composer-disabled", !!disabled);

    if (banner) {
        if (disabled) {
            banner.textContent = reasonMessage || "You cannot send messages in this chat.";
            banner.classList.remove("hidden");
        } else {
            banner.classList.add("hidden");
            banner.textContent = "";
        }
    }
}

function syncBlockButtonUI() {
    const blockBtn = document.getElementById("chat-block-btn");
    if (!blockBtn) return;
    blockBtn.setAttribute("data-is-blocked", isBlockedByCurrentUser ? "true" : "false");
    blockBtn.textContent = isBlockedByCurrentUser ? "✅ Unblock" : "🚫 Block";
}

function applyModerationEvent(data) {
    const chatUserId = document.getElementById("chat-user-id")?.value;
    if (!chatUserId || !currentUserId) return;

    const actorId = String(data.actor_id ?? "");
    const targetId = String(data.target_id ?? "");
    const selfId = String(currentUserId);
    const otherId = String(chatUserId);

    const affectsOpenChat =
        (actorId === selfId && targetId === otherId) ||
        (actorId === otherId && targetId === selfId);

    if (!affectsOpenChat) return;

    if (data.action === "block" && actorId === selfId && targetId === otherId) {
        isBlockedByCurrentUser = true;
        syncBlockButtonUI();
        showNotification("User blocked");
        return;
    }

    if (data.action === "unblock" && actorId === selfId && targetId === otherId) {
        isBlockedByCurrentUser = false;
        syncBlockButtonUI();
        showNotification("User unblocked");
        return;
    }

    if (data.action === "report") {
        if (actorId === selfId && targetId === otherId) {
            showNotification("Report sent. The user will be notified.");
            return;
        }
        if (actorId === otherId && targetId === selfId) {
            showNotification("This user reported you. Admin will review the account.");
            return;
        }
    }
}

function formatMessageTime(dateValue) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatDateLabel(dateValue) {
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    return date.toLocaleDateString([], {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
        year: 'numeric'
    });
}

function ensureDateSeparator(chatBox, dateValue) {
    if (!chatBox) return;
    const date = dateValue instanceof Date ? dateValue : new Date(dateValue);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const last = chatBox.dataset.lastDate || '';
    if (last === key) return;

    const separator = document.createElement('div');
    separator.className = 'date-separator';
    separator.textContent = formatDateLabel(date);
    chatBox.appendChild(separator);
    chatBox.dataset.lastDate = key;
}

function escapeHtml(text) {
    return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function getChatDisplayName() {
    return document.getElementById("chat-title")?.textContent?.trim() || "Chat";
}

function renderTextMessageCard({ messageId, messageText, isOwn, timeText, labelText = "", showActions = false, showTick = false, isRead = false }) {
    const safeMessage = escapeHtml(messageText);
    const safeLabel = escapeHtml(labelText || getChatDisplayName());
    const canShowActions = showActions && !!messageId;
    const actionsMarkup = canShowActions
        ? `<div class="message-actions"><button type="button" class="message-action-btn js-edit-message" data-message-id="${messageId}" data-message-text="${safeMessage}">Edit</button><button type="button" class="message-action-btn js-delete-message" data-message-id="${messageId}">Delete</button></div>`
        : "";
    const footerMarkup = showTick
        ? `<div class="text-right text-[11px] mt-1 opacity-85 tick tick-thin" data-id="${messageId}"><span class="tick-mark">${isRead ? "✓✓" : "✓"}</span><span class="message-time">${escapeHtml(timeText)}</span></div>`
        : `<div class="text-right text-[11px] mt-1 text-slate-500 message-time">${escapeHtml(timeText)}</div>`;

    return `
        <div class="${isOwn ? "flex justify-end" : "flex"} message-row ${isOwn ? "message-row-own" : "message-row-other"}" data-message-id="${messageId}">
            <div class="${isOwn ? "msg-own" : "msg-other"} p-3 rounded-2xl shadow-sm max-w-xs relative message-bubble ${isOwn ? "message-own" : "message-other"}" data-message-id="${messageId}">
                <div class="message-label">${isOwn ? "You" : safeLabel}</div>
                <div class="message-content">${safeMessage}</div>
                ${actionsMarkup}
                ${footerMarkup}
            </div>
        </div>
    `;
}

function appendMessageMarkup(chatBox, markup, dateValue) {
    ensureDateSeparator(chatBox, dateValue);
    const wrapper = document.createElement("div");
    wrapper.innerHTML = markup.trim();
    const element = wrapper.firstElementChild;
    if (element) {
        chatBox.appendChild(element);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}

function updateMessageCard(messageId, newText) {
    document.querySelectorAll(`.message-row[data-message-id="${messageId}"]`).forEach(node => {
        const content = node.querySelector(".message-content");
        if (content) content.textContent = newText;
        const footer = node.querySelector(".message-time")?.parentElement;
        if (footer && !footer.querySelector(".edited-badge")) {
            const editedBadge = document.createElement("span");
            editedBadge.className = "edited-badge ml-1 text-[10px] opacity-80";
            editedBadge.textContent = "(edited)";
            footer.appendChild(editedBadge);
        }
    });
}

function removeMessageCard(messageId) {
    document.querySelectorAll(`.message-row[data-message-id="${messageId}"]`).forEach(node => node.remove());
}


// =========================
// 🔥 CONNECT SOCKET
// =========================
function connectSocket(userId) {

    let currentUserField = document.getElementById("current-user-id");

    if (!currentUserField) {
        console.error("❌ current-user-id not found");
        return;
    }

    currentUserId = currentUserField.value;

    socket = new WebSocket(
        'ws://' + window.location.host + '/ws/chat/' + userId + '/?user_id=' + currentUserId
    );

    // =========================
    // 🔥 ON MESSAGE
    // =========================
    socket.onmessage = function(e) {

        const data = JSON.parse(e.data);
        const chatBox = document.getElementById("chat-box");

        // =========================
        // 🔥 TYPING EVENTS
        // =========================
        if (data.type === "typing") {
            if (String(data.sender) !== String(currentUserId)) {
                showTyping();
            }
            return;
        }

        if (data.type === "stop_typing") {
            hideTyping();
            return;
        }

        if (data.type === "error") {
            showNotification(data.message || "Action failed");
            return;
        }

        // =========================
        // 🔥 READ RECEIPT
        // =========================
        if (data.type === "read") {

            document.querySelectorAll(".tick").forEach(tick => {
                const marker = tick.querySelector(".tick-mark");
                if (marker) marker.textContent = "✓✓";
            });

            return;
        }

        // =========================
        // 🔥 ONLINE / OFFLINE ALL USERS
        // =========================
        if (data.type === "status" && Array.isArray(data.online_users)) {
            let users = document.querySelectorAll(".user-item");
            users.forEach(u => {
                let uid = u.getAttribute("data-user-id");
                let statusEl = u.querySelector(".user-status");
                if (!statusEl) return;
                if (data.online_users.map(String).includes(String(uid))) {
                    statusEl.innerText = "● online";
                    statusEl.className = "user-status text-green-400 text-xs";
                } else {
                    statusEl.innerText = "● offline";
                    statusEl.className = "user-status text-gray-500 text-xs";
                }
            });
            return;
        }

        if (data.type === "profile_update") {
            allUsers = allUsers.map(u => {
                if (String(u.id) !== String(data.user_id)) return u;
                return {
                    ...u,
                    name: data.name,
                    nameLower: String(data.name || "").toLowerCase(),
                    avatar_url: data.profile_picture_url || u.avatar_url,
                };
            });
            if (String(currentUserId || "") === String(data.user_id)) {
                const avatar = document.getElementById("current-user-avatar");
                const name = document.getElementById("current-user-name");
                if (avatar && data.profile_picture_url) {
                    avatar.src = data.profile_picture_url;
                }
                if (name && data.name) {
                    name.textContent = data.name;
                }
            }
            renderUserList(document.getElementById("search-input")?.value.toLowerCase().trim() || "");
            return;
        }

        if (data.type === "moderation") {
            applyModerationEvent(data);
            return;
        }
        // =========================
        // 🔥 NEW MESSAGE
        // =========================
        if (data.type === "message") {
            const incomingSenderId = String(data.sender_id ?? data.sender ?? "");
            const messageDate = data.timestamp ? new Date(data.timestamp) : new Date();

            // 🔊 SOUND + NOTIFICATION (only if other user)
            if (incomingSenderId !== String(currentUserId)) {

                let sound = document.getElementById("msg-sound");
                if (sound) sound.play();

                showNotification("💬 " + data.message);

                // 🔥 MARK READ (IMPORTANT FIX)
                socket.send(JSON.stringify({
                    type: "read_messages"
                }));
            }

            // =========================
            // 🔥 MESSAGE UI
            // =========================
            if (incomingSenderId === String(currentUserId)) {
                appendMessageMarkup(chatBox, renderTextMessageCard({
                    messageId: data.msg_id,
                    messageText: data.message,
                    isOwn: true,
                    timeText: formatMessageTime(messageDate),
                    labelText: "You",
                    showActions: true,
                    showTick: true,
                    isRead: false,
                }), messageDate);

                if (data.local_only) {
                    showNotification("This message is visible only to you.");
                }

            } else {
                appendMessageMarkup(chatBox, renderTextMessageCard({
                    messageId: data.msg_id,
                    messageText: data.message,
                    isOwn: false,
                    timeText: formatMessageTime(messageDate),
                    labelText: data.sender_name || getChatDisplayName(),
                    showActions: false,
                    showTick: false,
                }), messageDate);
            }
        }
    };

    socket.onopen = function() {
        console.log("✅ WebSocket connected");
    };

    socket.onclose = function() {
        console.log("❌ WebSocket disconnected");
    };

    socket.onerror = function(e) {
        console.error("❌ Socket error", e);
    };
}


// =========================
// 🔥 SEND MESSAGE
// =========================

function sendMessage(e) {
    e.preventDefault();

    let input = document.getElementById("message-input");
    let fileInput = document.getElementById("file-input");
    let message = input.value;
    let file = fileInput.files[0];
    let receiverId = document.getElementById("chat-user-id")?.value;

    if (!message.trim() && !file) return;

    // If file is selected, use AJAX to send
    if (file) {
        let formData = new FormData();
        formData.append("message", message);
        formData.append("file", file);
        formData.append("receiver_id", receiverId);

        fetch("/send-message/", {
            method: "POST",
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCSRFToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showNotification(data.error);
                return;
            }
            // Show file in chat
            appendFileMessage(data, true);
            if (data.local_only) {
                showNotification("This message is visible only to you.");
            }
            input.value = "";
            fileInput.value = "";
        })
        .catch(err => {
            showNotification("File upload failed");
        });
        return;
    }

    // If only text, use WebSocket
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        console.log("❌ Socket not ready");
        return;
    }

    socket.send(JSON.stringify({
        message: message
    }));

    input.value = "";
}

function appendFileMessage(data, isOwn) {
    let chatBox = document.getElementById("chat-box");
    const messageDate = data.timestamp ? new Date(data.timestamp) : new Date();
    const canEditOrDelete = !!data.message_id;
    let fileHtml = "";
    if (data.file_url) {
        let ext = data.file_url.split('.').pop().toLowerCase();
        if (["jpg","jpeg","png","gif","webp","bmp","svg"].includes(ext)) {
            fileHtml = `<img src="${data.file_url}" alt="file" class="max-w-xs max-h-40 rounded mb-1" />`;
        } else if (["mp3","wav","ogg","aac","m4a"].includes(ext)) {
            fileHtml = `<audio controls src="${data.file_url}" class="mb-1"></audio>`;
        } else if (["mp4","avi","mov","wmv","flv","mkv","webm"].includes(ext)) {
            fileHtml = `<video controls src="${data.file_url}" class="max-w-xs max-h-40 mb-1"></video>`;
        } else {
            fileHtml = `<a href="${data.file_url}" target="_blank" class="text-blue-600 underline">${data.file_name || "Download file"}</a>`;
        }
    }
    const labelText = getChatDisplayName();
    const markup = `
        <div class="${isOwn ? 'flex justify-end' : 'flex'} message-row ${isOwn ? 'message-row-own' : 'message-row-other'}" data-message-id="${data.message_id || ''}">
            <div class="${isOwn ? 'msg-own' : 'msg-other'} p-3 rounded-2xl shadow max-w-xs relative message-bubble ${isOwn ? 'message-own' : 'message-other'}" data-message-id="${data.message_id || ''}">
                <div class="message-label">${isOwn ? 'You' : escapeHtml(labelText)}</div>
                ${fileHtml}
                ${data.message ? `<div class="message-content">${escapeHtml(data.message)}</div>` : ""}
                ${isOwn && canEditOrDelete ? `<div class="message-actions"><button type="button" class="message-action-btn js-edit-message" data-message-id="${data.message_id}" data-message-text="${escapeHtml(data.message || '')}">Edit</button><button type="button" class="message-action-btn js-delete-message" data-message-id="${data.message_id}">Delete</button></div>` : ""}
                ${isOwn
                    ? `<div class="text-[11px] text-right mt-1 opacity-85 tick tick-thin"><span class="tick-mark">✓</span><span class="message-time">${formatMessageTime(messageDate)}</span></div>`
                    : `<div class="text-[11px] text-right mt-1 text-slate-500 message-time">${formatMessageTime(messageDate)}</div>`}
            </div>
        </div>
    `;
    appendMessageMarkup(chatBox, markup, messageDate);
}

function getCSRFToken() {
    let name = 'csrftoken';
    let cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
        let c = cookies[i].trim();
        if (c.startsWith(name + '=')) {
            return decodeURIComponent(c.substring(name.length + 1));
        }
    }
    return '';
}


// =========================
// 🔥 TYPING SEND
// =========================
let typingTimeout = null;

document.addEventListener("DOMContentLoaded", function () {

    let input = document.getElementById("message-input");

    if (!input) return;

    input.addEventListener("input", function () {

        if (!socket || socket.readyState !== WebSocket.OPEN) return;

        socket.send(JSON.stringify({
            type: 'typing'
        }));

        clearTimeout(typingTimeout);

        typingTimeout = setTimeout(() => {
            socket.send(JSON.stringify({
                type: 'stop_typing'
            }));
        }, 800);

    });

});

document.addEventListener("DOMContentLoaded", function () {
    const emojiToggle = document.getElementById("emoji-toggle");
    const emojiPanel = document.getElementById("emoji-panel");
    const emojiRecent = document.getElementById("emoji-recent");
    const emojiAll = document.getElementById("emoji-all");
    const emojiTabRecent = document.getElementById("emoji-tab-recent");
    const emojiTabAll = document.getElementById("emoji-tab-all");
    const emojiRecentView = document.getElementById("emoji-recent-view");
    const emojiAllView = document.getElementById("emoji-all-view");
    const messageInput = document.getElementById("message-input");
    if (!emojiToggle || !emojiPanel || !emojiRecent || !emojiAll || !emojiTabRecent || !emojiTabAll || !emojiRecentView || !emojiAllView || !messageInput) return;

    const RECENT_EMOJI_KEY = "charchadesk_recent_emojis";
    const EMOJI_CATALOG = [
        "😀","😁","😂","🤣","😊","🙂","😉","😍","😘","😎","🤩","🥳","🤔","🤗","😴","😢",
        "😭","😡","🤯","😇","🙌","👏","👍","👎","👌","🙏","💪","🔥","✨","⭐","🎉","❤️",
        "💙","💚","💛","🧡","💜","🤍","🖤","💯","✅","❌","⚡","🌈","☀️","🌙","🍕","☕",
        "🍫","🎵","🎧","📚","💻","📱","🚀","🎯","🏆","⚽","🏏","🎮","🐶","🐱","🌸","🍀"
    ];

    function getRecentEmojis() {
        try {
            const raw = localStorage.getItem(RECENT_EMOJI_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed : [];
        } catch {
            return [];
        }
    }

    function saveRecentEmojis(list) {
        localStorage.setItem(RECENT_EMOJI_KEY, JSON.stringify(list.slice(0, 24)));
    }

    function createEmojiButton(emoji) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "emoji-item";
        btn.textContent = emoji;
        btn.addEventListener("click", function () {
            const start = messageInput.selectionStart ?? messageInput.value.length;
            const end = messageInput.selectionEnd ?? messageInput.value.length;
            messageInput.value = messageInput.value.slice(0, start) + emoji + messageInput.value.slice(end);
            const nextPos = start + emoji.length;
            messageInput.focus();
            messageInput.setSelectionRange(nextPos, nextPos);

            const recent = getRecentEmojis().filter(item => item !== emoji);
            recent.unshift(emoji);
            saveRecentEmojis(recent);
            renderRecent();
        });
        return btn;
    }

    function renderRecent() {
        const recent = getRecentEmojis();
        emojiRecent.innerHTML = "";
        if (!recent.length) {
            const hint = document.createElement("span");
            hint.className = "text-xs text-slate-400 col-span-8";
            hint.textContent = "No recent emojis yet";
            emojiRecent.appendChild(hint);
            return;
        }
        recent.slice(0, 16).forEach(emoji => emojiRecent.appendChild(createEmojiButton(emoji)));
    }

    function renderAll() {
        emojiAll.innerHTML = "";
        EMOJI_CATALOG.forEach(emoji => emojiAll.appendChild(createEmojiButton(emoji)));
    }

    function setEmojiView(viewName) {
        const showRecent = viewName === "recent";
        emojiRecentView.classList.toggle("hidden", !showRecent);
        emojiAllView.classList.toggle("hidden", showRecent);
        emojiTabRecent.classList.toggle("active", showRecent);
        emojiTabAll.classList.toggle("active", !showRecent);
    }

    renderRecent();
    renderAll();
    setEmojiView("recent");

    emojiToggle.addEventListener("click", function (e) {
        e.stopPropagation();
        emojiPanel.classList.toggle("hidden");
        if (!emojiPanel.classList.contains("hidden")) {
            setEmojiView("recent");
            renderRecent();
        }
    });

    emojiTabRecent.addEventListener("click", function (e) {
        e.stopPropagation();
        setEmojiView("recent");
    });

    emojiTabAll.addEventListener("click", function (e) {
        e.stopPropagation();
        setEmojiView("all");
    });

    document.addEventListener("click", function (e) {
        if (!e.target.closest("#emoji-panel, #emoji-toggle")) {
            emojiPanel.classList.add("hidden");
        }
    });
});


// =========================
// 🔥 AUTO CONNECT
// =========================
document.addEventListener("DOMContentLoaded", function () {

    let userField = document.getElementById("chat-user-id");
    let currentUserField = document.getElementById("current-user-id");

    if (userField) {
        connectSocket(userField.value);
    } else if (currentUserField) {
        connectSocket(currentUserField.value);
    }

});


// =========================
// 🔥 TYPING UI
// =========================
function showTyping() {
    // Show typing indicator in the chat header (top left)
    let typingStatus = document.getElementById("typing-status");
    if (typingStatus) {
        typingStatus.innerText = "Typing...";
    }
}

function hideTyping() {
    let typingStatus = document.getElementById("typing-status");
    if (typingStatus) {
        typingStatus.innerText = "";
    }
}


// =========================
// 🔔 NOTIFICATION
// =========================
function showNotification(message) {

    let container = document.getElementById("notification-container");

    let notif = document.createElement("div");

    notif.className = `
        bg-black text-white px-4 py-3 rounded shadow-lg
        animate-pulse
    `;

    notif.innerText = message;

    container.appendChild(notif);

    setTimeout(() => {
        notif.remove();
    }, 3000);
}


// =========================
// 🔽 DROPDOWN
// =========================
function toggleAccountMenu(event) {
    if (event) event.stopPropagation();
    let accountMenu = document.getElementById("account-menu");
    let chatMenu = document.getElementById("menu");
    if (chatMenu) chatMenu.classList.add("hidden");
    if (accountMenu) accountMenu.classList.toggle("hidden");
}

function toggleMenu(event) {
    if (event) event.stopPropagation();
    let menu = document.getElementById("menu");
    let accountMenu = document.getElementById("account-menu");
    if (accountMenu) accountMenu.classList.add("hidden");
    if (menu) menu.classList.toggle("hidden");
}

function viewProfile(userId) {
    window.location.href = `/view-profile/${userId}/`;
}

document.addEventListener("DOMContentLoaded", function () {
    const accountMenu = document.getElementById("account-menu");
    const chatMenu = document.getElementById("menu");
    const blockBtn = document.getElementById("chat-block-btn");
    const deleteBtn = document.getElementById("chat-delete-btn");
    const reportBtn = document.getElementById("chat-report-btn");

    isBlockedByCurrentUser = blockBtn?.getAttribute("data-is-blocked") === "true";
    syncBlockButtonUI();

    if (accountMenu) {
        accountMenu.addEventListener("click", function (e) {
            e.stopPropagation();
        });
    }

    if (chatMenu) {
        chatMenu.addEventListener("click", function (e) {
            e.stopPropagation();
        });
    }

    if (reportBtn) {
        reportBtn.addEventListener("click", function () {
            const userId = reportBtn.getAttribute("data-user-id");
            if (!userId) return;
            if (!confirm("Report this user? This will notify them and send it to moderation.")) return;

            const body = new URLSearchParams();
            body.append("user_id", userId);

            fetch("/report-user/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": getCSRFToken()
                },
                body
            })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        showNotification(data.error);
                        return;
                    }
                    showNotification("Report sent");
                })
                .catch(() => showNotification("Report action failed"));
        });
    }

    if (blockBtn) {
        blockBtn.addEventListener("click", function () {
            const userId = blockBtn.getAttribute("data-user-id");
            const isBlocked = blockBtn.getAttribute("data-is-blocked") === "true";
            if (!userId) return;
            const endpoint = isBlocked ? "/unblock-user/" : "/block-user/";
            const actionText = isBlocked ? "Unblock" : "Block";
            const confirmText = isBlocked
                ? "Unblock this user?"
                : "Block this user? Incoming messages from this user will be hidden for you.";
            if (!confirm(confirmText)) return;

            const body = new URLSearchParams();
            body.append("user_id", userId);

            fetch(endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": getCSRFToken()
                },
                body
            })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        showNotification(data.error);
                        return;
                    }
                    showNotification(`${actionText} request sent`);
                })
                .catch(() => showNotification(`${actionText} action failed`));
        });
    }

    if (deleteBtn) {
        deleteBtn.addEventListener("click", function () {
            const userId = deleteBtn.getAttribute("data-user-id");
            if (!userId) return;
            if (!confirm("Delete all messages in this chat?")) return;

            const body = new URLSearchParams();
            body.append("user_id", userId);

            fetch("/delete-chat/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": getCSRFToken()
                },
                body
            })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        showNotification(data.error);
                        return;
                    }
                    showNotification("Chat deleted");
                    window.location.reload();
                })
                .catch(() => showNotification("Delete chat failed"));
        });
    }
});

document.addEventListener("click", function (e) {
    const editButton = e.target.closest(".js-edit-message");
    const deleteButton = e.target.closest(".js-delete-message");

    if (editButton) {
        const messageId = editButton.getAttribute("data-message-id");
        const currentText = editButton.getAttribute("data-message-text") || "";
        const newText = prompt("Edit message", currentText);
        if (newText === null) return;

        const body = new URLSearchParams();
        body.append("message_id", messageId);
        body.append("message", newText);

        fetch("/edit-message/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": getCSRFToken()
            },
            body
        })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showNotification(data.error);
                    return;
                }
                updateMessageCard(messageId, newText);
                showNotification("Message updated");
            })
            .catch(() => showNotification("Edit failed"));
        return;
    }

    if (deleteButton) {
        const messageId = deleteButton.getAttribute("data-message-id");
        if (!confirm("Delete this message?")) return;

        const body = new URLSearchParams();
        body.append("message_id", messageId);

        fetch("/delete-message/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": getCSRFToken()
            },
            body
        })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showNotification(data.error);
                    return;
                }
                removeMessageCard(messageId);
                showNotification("Message deleted");
            })
            .catch(() => showNotification("Delete failed"));
    }
});


// =========================
// 🔽 CLOSE DROPDOWN
// =========================
document.addEventListener("click", function(e) {
    let menu = document.getElementById("menu");
    let accountMenu = document.getElementById("account-menu");
    const isMenuAreaClick = e.target.closest("#menu, #chat-menu-button, #account-menu, #account-menu-button");
    if (isMenuAreaClick) return;
    if (menu) menu.classList.add("hidden");
    if (accountMenu) accountMenu.classList.add("hidden");
});


// =========================
// AI CHAT SUMMARY
// =========================
document.addEventListener("DOMContentLoaded", function () {
    const openBtn = document.getElementById("open-summary-modal");
    const summaryModal = document.getElementById("summary-modal");
    const closeSummaryModalBtn = document.getElementById("close-summary-modal");
    const quickButtons = document.querySelectorAll(".summary-quick-btn");
    const advancedToggle = document.getElementById("toggle-summary-advanced");
    const advancedPanel = document.getElementById("summary-advanced-panel");
    const startInput = document.getElementById("summary-start");
    const endInput = document.getElementById("summary-end");
    const languageInput = document.getElementById("summary-language");
    const getSummaryBtn = document.getElementById("get-summary-btn");

    const resultModal = document.getElementById("summary-result-modal");
    const closeResultBtn = document.getElementById("close-summary-result");
    const resultContent = document.getElementById("summary-result-content");
    const chatUserId = document.getElementById("chat-user-id")?.value;

    if (!openBtn || !summaryModal || !resultModal || !chatUserId) return;

    let selectedRange = "last_1_hour";
    let isAdvancedOpen = false;

    function toLocalInputValue(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        const hours = String(date.getHours()).padStart(2, "0");
        const minutes = String(date.getMinutes()).padStart(2, "0");
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }

    function toISOFromLocalInput(localInputValue) {
        if (!localInputValue) return "";
        const parsed = new Date(localInputValue);
        if (Number.isNaN(parsed.getTime())) return "";
        return parsed.toISOString();
    }

    function getRangeFromPreset(preset) {
        const now = new Date();
        const end = new Date(now);
        const start = new Date(now);

        if (preset === "last_1_hour") {
            start.setHours(start.getHours() - 1);
        } else if (preset === "last_2_hour") {
            start.setHours(start.getHours() - 2);
        } else if (preset === "last_3_hour") {
            start.setHours(start.getHours() - 3);
        } else if (preset === "today") {
            start.setHours(0, 0, 0, 0);
        } else if (preset === "yesterday") {
            const yStart = new Date(now);
            yStart.setDate(now.getDate() - 1);
            yStart.setHours(0, 0, 0, 0);

            const yEnd = new Date(now);
            yEnd.setDate(now.getDate() - 1);
            yEnd.setHours(23, 59, 0, 0);

            return { start: yStart, end: yEnd };
        } else if (preset === "last_7_days") {
            start.setDate(start.getDate() - 7);
        }

        return { start, end };
    }

    function highlightSelectedQuickButton() {
        quickButtons.forEach((btn) => {
            const active = btn.getAttribute("data-range") === selectedRange;
            btn.classList.toggle("bg-cyan-50", active);
            btn.classList.toggle("border-cyan-300", active);
            btn.classList.toggle("text-cyan-900", active);
        });
    }

    function setDefaultAdvancedValues() {
        const range = getRangeFromPreset(selectedRange);
        if (startInput) startInput.value = toLocalInputValue(range.start);
        if (endInput) endInput.value = toLocalInputValue(range.end);
    }

    function openSummaryModal() {
        summaryModal.classList.remove("hidden");
        isAdvancedOpen = false;
        if (advancedPanel) advancedPanel.classList.add("hidden");
        if (advancedToggle) advancedToggle.textContent = "Advanced";
        highlightSelectedQuickButton();
        setDefaultAdvancedValues();
    }

    function closeSummaryModal() {
        summaryModal.classList.add("hidden");
    }

    function openResultModal(content) {
        if (resultContent) {
            const safeText = String(content || "");
            const lines = safeText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
            const escapeHtml = (text) => String(text)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#39;");

            const rendered = lines.map((line, index) => {
                const isHeading = index === 0 || /^\*\*.*\*\*$/.test(line) || /^(summary|सारांश)/i.test(line) || /^(summary|सारांश)\s*[:：]/i.test(line);
                const plainLine = line.replace(/^\*\*(.*)\*\*$/, "$1");
                if (isHeading) {
                    return `<div class="mb-3 text-base font-bold text-slate-900">${escapeHtml(plainLine.replace(/[:：]\s*$/, ""))}</div>`;
                }

                const bulletText = plainLine.replace(/^[-•]\s*/, "");
                return `<div class="mb-2 leading-6 text-slate-700"><span class="font-semibold text-slate-900">•</span> ${escapeHtml(bulletText)}</div>`;
            }).join("");

            resultContent.innerHTML = rendered || `<div class="text-slate-700">${escapeHtml(safeText)}</div>`;
        }
        resultModal.classList.remove("hidden");
    }

    function closeResultModal() {
        resultModal.classList.add("hidden");
    }

    openBtn.addEventListener("click", openSummaryModal);
    closeSummaryModalBtn?.addEventListener("click", closeSummaryModal);
    closeResultBtn?.addEventListener("click", closeResultModal);

    summaryModal.addEventListener("click", function (e) {
        if (e.target === summaryModal) closeSummaryModal();
    });

    resultModal.addEventListener("click", function (e) {
        if (e.target === resultModal) closeResultModal();
    });

    quickButtons.forEach((btn) => {
        btn.addEventListener("click", function () {
            selectedRange = btn.getAttribute("data-range") || "last_1_hour";
            highlightSelectedQuickButton();
            setDefaultAdvancedValues();
        });
    });

    advancedToggle?.addEventListener("click", function () {
        isAdvancedOpen = !isAdvancedOpen;
        if (advancedPanel) advancedPanel.classList.toggle("hidden", !isAdvancedOpen);
        advancedToggle.textContent = isAdvancedOpen ? "Hide Advanced" : "Advanced";
    });

    getSummaryBtn?.addEventListener("click", function () {
        const usingAdvanced = isAdvancedOpen;
        let startValue = "";
        let endValue = "";

        if (usingAdvanced) {
            startValue = toISOFromLocalInput(startInput?.value || "");
            endValue = toISOFromLocalInput(endInput?.value || "");
        } else {
            const range = getRangeFromPreset(selectedRange);
            startValue = range.start.toISOString();
            endValue = range.end.toISOString();
        }

        if (!startValue || !endValue) {
            showNotification("Please select valid date/time range");
            return;
        }

        const body = new URLSearchParams();
        body.append("user_id", chatUserId);
        body.append("start_datetime", startValue);
        body.append("end_datetime", endValue);
        body.append("language", languageInput?.value || "English");

        getSummaryBtn.disabled = true;
        getSummaryBtn.textContent = "Generating...";

        fetch("/summarize-chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": getCSRFToken(),
            },
            body,
        })
            .then((response) => response.json())
            .then((data) => {
                if (data.error) {
                    showNotification(data.error);
                    return;
                }

                closeSummaryModal();
                openResultModal(data.summary || "No summary available.");
            })
            .catch(() => {
                showNotification("Failed to summarize chat");
            })
            .finally(() => {
                getSummaryBtn.disabled = false;
                getSummaryBtn.textContent = "Get Summary";
            });
    });
});

