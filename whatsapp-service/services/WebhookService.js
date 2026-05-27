const axios = require("axios");
const crypto = require("crypto");
const config = require("../config");

class LLMService {
  // We pass the db repository here to fetch config dynamically
  async triggerLLMService(messageId, db) {
    const url_config = await db.getActiveWebhook();

    if (!url_config) {
      console.warn("⚠️ No active webhook configuration found.");
      return;
    }
    const payload = {
      id: messageId,
    };

    // Advanced: Create a signature using the secret from DB
    const signature = crypto
      .createHmac("sha256", url_config.secret)
      .update(JSON.stringify(payload))
      .digest("hex");

    let attempts = 0;
    while (attempts < url_config.retries) {
      try {
        await axios.post(`${url_config.url}`, payload, {
          headers: {
            "X-Hub-Signature-256": `sha256=${signature}`,
            "Content-Type": "application/json",
          },
        });
        console.log(`✅ Webhook sent to ${url_config.url}`);
        break; // Success! Exit retry loop
      } catch (error) {
        attempts++;
        console.error(
          `❌ Webhook attempt ${attempts} failed: ${error.message}`
        );
        if (attempts >= config.retries) console.error("Final retry failed.");
      }
    }
  }
}

module.exports = new LLMService();
