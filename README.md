# ai-conversation
To save every user query and AI response to a database, you need to intercept the data inside your backend application right before sending the prompt to the AI and immediately after receiving the reply. Because LLM APIs are stateless, your server acts as the bridge that logs the conversation
