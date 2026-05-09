const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const fs = require('fs');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// Static files တွေအလုပ်လုပ်ဖို့ (Socket.io အပါအဝင်)
app.use(express.static(__dirname));
app.use(express.json());

// Folder မခွဲထားတဲ့အတွက် လက်ရှိ Directory ထဲက HTML ဖိုင်တွေကို တိုက်ရိုက်ခေါ်ပေးမယ်
app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'admin.html')));
app.get('/admin.html', (req, res) => res.sendFile(path.join(__dirname, 'admin.html')));
app.get('/user.html', (req, res) => res.sendFile(path.join(__dirname, 'user.html')));
app.get('/outline.html', (req, res) => res.sendFile(path.join(__dirname, 'outline.html')));
app.get('/vless.html', (req, res) => res.sendFile(path.join(__dirname, 'vless.html')));

const DB_FILE = './data.json';
let db = { users: {}, admin_config: {} };

// Database ဖတ်ခြင်း
if (fs.existsSync(DB_FILE)) {
    db = JSON.parse(fs.readFileSync(DB_FILE));
} else {
    saveDB(); // မရှိရင် data.json အသစ်ဖန်တီးမယ်
}

function saveDB() {
    fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2));
}

// Python API Sync အတွက် Webhooks
app.get('/api/sync-data', (req, res) => {
    res.json(db);
});

app.post('/api/sync-update', (req, res) => {
    const { update_fields } = req.body;
    let changed = false;
    for (const [userId, fields] of Object.entries(update_fields)) {
        if (db.users[userId]) {
            db.users[userId] = { ...db.users[userId], ...fields };
            io.to(userId).emit('user_data_update', db.users[userId]); 
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
            socket.join(username); 
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
        socket.emit('admin_config_data', db.admin_config?.server_api || {});
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

server.listen(3000, () => console.log('🚀 Gateway Server running on port 3000'));
