# 🚀 ASTRAL AI API

AI-powered modpack builder API for Minecraft launchers using RAG architecture.

## 🌟 Features

- **Semantic Search**: Vector-based mod search using sentence-transformers embeddings
- **DeepSeek AI**: Intelligent mod selection and reasoning
- **Supabase + pgvector**: Fast similarity search across 500+ mods
- **RAG Architecture**: Retrieval-Augmented Generation for optimal results

## 📡 Endpoints

### `POST /api/ai/organize`
Organize mods into smart categories

### `POST /api/ai/build`
Build modpack from user prompt

### `POST /api/ai/build-board`
Generate `board_state.json` ready for import

## 🔧 Tech Stack

- **Flask** - REST API framework
- **DeepSeek** - LLM for reasoning
- **Supabase** - PostgreSQL + pgvector
- **sentence-transformers** - Local embeddings (all-MiniLM-L6-v2)
- **Vercel** - Serverless deployment

## 🚀 Deploy to Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/yourusername/astral-ai-api)

### Environment Variables

```env
DEEPSEEK_API_KEY=your_deepseek_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

## 💻 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
python api/index.py
```

Server will start on `http://localhost:5000`

## 📊 Architecture

```
User Prompt → Semantic Search (100 candidates) → DeepSeek AI (15 best) → board_state.json
```

## 📝 License

MIT

---

Built with ❤️ for the Minecraft modding community