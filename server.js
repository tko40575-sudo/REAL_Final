const express = require('express');
const fs = require('fs');
const path = require('path');
const session = require('express-session');
const bodyParser = require('body-parser');

const app = express();
const PORT = 3000;

// Middleware များ
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));
app.use(express.static('public')); // Frontend ဖိုင်များအတွက်
app.use(session({
    secret: 'mock-bank-secure-key',
    resave: false,
    saveUninitialized: true
}));

const DB_FILE = './users.json';

// User များကို ဖတ်ရန်/သိမ်းရန် Function များ
const getUsers = () => JSON.parse(fs.readFileSync(DB_FILE));
const saveUsers = (users) => fs.writeFileSync(DB_FILE, JSON.stringify(users, null, 2));

// ၁။ အကောင့်အသစ်ဖွင့်ခြင်း (Registration)
app.post('/api/register', (req, res) => {
    const { username, password, cardNumber, securityKey, expireDate } = req.body;
    const users = getUsers();

    if (users.find(u => u.username === username || u.cardNumber === cardNumber)) {
        return res.status(400).json({ error: 'Username or Card Number already exists!' });
    }

    // Dummy အကောင့်တစ်ခု ဖန်တီးခြင်း (လက်ကျန်ငွေနှင့် မှတ်တမ်းအတုများ ပါဝင်သည်)
    const newUser = {
        id: Date.now().toString(),
        username,
        password,
        cardNumber,
        securityKey,
        expireDate,
        balance: Math.floor(Math.random() * 5000) + 1000, // $1000 မှ $6000 ကြား
        transactions: [
            { date: new Date().toLocaleDateString(), description: 'Initial Deposit', amount: 3000, type: 'credit' },
            { date: new Date().toLocaleDateString(), description: 'Netflix Subscription', amount: -15.99, type: 'debit' },
            { date: new Date().toLocaleDateString(), description: 'Amazon Shopping', amount: -120.50, type: 'debit' }
        ]
    };

    users.push(newUser);
    saveUsers(users);
    res.json({ success: true, message: 'Account created successfully!' });
});

// ၂။ အကောင့်ဝင်ခြင်း (Login)
app.post('/api/login', (req, res) => {
    const { username, password, cardNumber } = req.body;
    const users = getUsers();

    // Username, Password နဲ့ Card Number ၃ ခုလုံး မှန်ကန်မှုစစ်ဆေးခြင်း
    const user = users.find(u => u.username === username && u.password === password && u.cardNumber === cardNumber);

    if (user) {
        req.session.userId = user.id;
        res.json({ success: true });
    } else {
        res.status(401).json({ error: 'Invalid credentials! Please check your details.' });
    }
});

// ၃။ အကောင့်အချက်အလက် ဆွဲယူခြင်း (Dashboard အတွက်)
app.get('/api/userdata', (req, res) => {
    if (!req.session.userId) return res.status(401).json({ error: 'Unauthorized' });
    
    const users = getUsers();
    const user = users.find(u => u.id === req.session.userId);
    
    if (user) {
        const { password, securityKey, ...safeUser } = user; // လုံခြုံရေးအရ Password များကို ဖျောက်ထားသည်
        res.json(safeUser);
    } else {
        res.status(404).json({ error: 'User not found' });
    }
});

// ၄။ အကောင့်ထွက်ခြင်း (Logout)
app.post('/api/logout', (req, res) => {
    req.session.destroy();
    res.json({ success: true });
});

app.listen(PORT, () => {
    console.log(`🚀 Mock Bank Server is running on http://localhost:${PORT}`);
});
