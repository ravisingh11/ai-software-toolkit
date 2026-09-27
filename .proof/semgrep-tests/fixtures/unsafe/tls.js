const https = require("https");

// ruleid: proof.javascript-disabled-tls-verification
new https.Agent({ rejectUnauthorized: false });
