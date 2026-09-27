const https = require("https");

// ok: proof.javascript-disabled-tls-verification
new https.Agent({ rejectUnauthorized: true });
