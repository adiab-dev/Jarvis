# Tauri + React + Typescript

This template should help get you started developing with Tauri, React and Typescript in Vite.

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)

## Ollama chat model

The backend uses a custom Ollama model named `jarvis`. Its system prompt is defined in `backend/Modelfile`.

1. Install and start [Ollama](https://ollama.com/download).
2. In PowerShell, from the project folder, create the model:

   ```powershell
   .\backend\setup_model.ps1
   ```

   This creates `jarvis` from `qwen3.5:4b`; Ollama downloads the base model if needed.
3. Start the app/backend as usual. The `/chat` endpoint sends requests to the `jarvis` model.

After changing the prompt or base model in `backend/Modelfile`, rerun the setup command to rebuild `jarvis`.

## Live web search (Tavily)

The backend can search the web through Tavily. It uses Tavily's Basic search mode to spend one credit per search and returns source titles, URLs, and summaries to the local Ollama model. Tavily's free plan currently provides 1,000 credits per month without requiring payment details; searches stop when the monthly allowance is exhausted.

1. Create a free account at [Tavily](https://app.tavily.com/) and copy an API key from the dashboard's API Keys section.
2. In Windows, open **Edit environment variables for your account** from Start. Under **User variables**, choose **New** and set:
   - Variable name: `TAVILY_API_KEY`
   - Variable value: your Tavily API key
3. Save the change and fully restart Jarvis (including any open terminal or development server), so the backend receives the new variable.
4. Ask Jarvis to search for something current, such as “Search the web for today's … and cite your sources.”

Keep the key in the environment variable; do not put it in chat messages or source files. Search queries are sent to Tavily, while the model and the rest of the app remain local.

