const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const fs = require('fs');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

app.use(express.static('public')); // သင့် HTML ဖိုင်များကို public folder ထဲထည့်ပါ
app.use(express.json());

const DB_FILE = './data.json';
let db = { users: {}, admin_config: {} };

// Database ဖတ်ခြင်း
if (fs.existsSync(DB_FILE)) {
    db = JSON.parse(fs.readFileSync(DB_FILE));
}

// Database သိမ်းခြင်း
function saveDB() {
    fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
}

// Python API Sync အတွက် Webhook
app.get('/api/sync-data', (req, res) => {
    res.json(db);
});

app.post('/api/sync-update', (req, res) => {
    const { update_fields } = req.body;
    let changed = false;
    for (const [userId, fields] of Object.entries(update_fields)) {
        if (db.users[userId]) {
            db.users[userId] = { ...db.users[userId], ...fields };
            io.to(userId).emit('user_data_update', db.users[userId]); // User ဆီ ချက်ချင်း Update လှမ်းပို့ပါမယ်
            changed = true;
        }
    }
    if (changed) {
        saveDB();
        io.emit('admin_all_users_data', db.users);
    }
    res.json({ success: true });
});

// Socket.io Real-time ချိတ်ဆက်မှုများ
io.on('connection', (socket) => {
    // ---- [ User အပိုင်း ] ----
    socket.on('user_login', ({ username, deviceOS }) => {
        const user = db.users[username];
        if (user) {
            db.users[username].lastActive = new Date().toISOString();
            db.users[username].deviceOS = deviceOS || user.deviceOS;
            saveDB();
            
            socket.emit('user_login_response', { exists: true, username, data: db.users[username] });
            socket.join(username); // အချိန်ပြည့် Update ရဖို့ Room ထဲဝင်ပါမယ်
        } else {
            socket.emit('user_login_response', { exists: false });
        }
    });

    socket.on('join_user_room', ({ username, deviceOS }) => {
        socket.join(username);
        if (db.users[username]) {
            if(deviceOS) db.users[username].deviceOS = deviceOS;
            saveDB();
            socket.emit('user_data_update', db.users[username]);
        } else {
            socket.emit('user_not_found');
        }
    });

    socket.on('update_user_name', ({ username, displayName }) => {
        if (db.users[username]) {
            db.users[username].displayName = displayName;
            saveDB();
            io.to(username).emit('user_data_update', db.users[username]);
            io.emit('admin_all_users_data', db.users);
        }
    });

    // ---- [ Admin အပိုင်း ] ----
    socket.on('admin_get_config', () => {
        socket.emit('admin_config_data', db.admin_config.server_api || {});
    });

    socket.on('admin_save_config', (config) => {
        db.admin_config.server_api = config;
        saveDB();
    });

    socket.on('admin_fetch_user', (username) => {
        const data = db.users[username];
        socket.emit('admin_user_data', { id: username, exists: !!data, data: data || {} });
    });

    socket.on('admin_save_user', ({ username, data }) => {
        db.users[username] = { ...db.users[username], ...data };
        saveDB();
        socket.emit('admin_save_success');
        io.to(username).emit('user_data_update', db.users[username]); 
        io.emit('admin_all_users_data', db.users); 
    });

    socket.on('admin_get_all_users', () => {
        socket.emit('admin_all_users_data', db.users);
    });
});

server.listen(3000, () => console.log('🚀 Gateway & WebSocket Server running on port 3000'));
