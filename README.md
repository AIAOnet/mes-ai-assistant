# MES AI Assistant

A local MES factory simulation that demonstrates how machine data can flow through industrial communication, persistence, monitoring, and a governed AI assistant.

## Included components

- Machine and PLC simulation
- OPC UA and MQTT communication
- SQL Server persistence
- FastAPI dashboard with live WebSocket updates
- Alarm, maintenance, production, and OEE workflows
- Role-based access and an OpenAI-compatible assistant
- Retrieval-augmented generation (RAG) and ontology search

## Quick start

Requirements: Docker Desktop with Docker Compose.

```powershell
git clone https://github.com/AIAOnet/mes-ai-assistant.git
cd mes-ai-assistant
Copy-Item .env.example .env
docker compose up -d --build
```

On macOS or Linux, replace the copy command with:

```bash
cp .env.example .env
```

### Configure `.env`

The values copied from `.env.example` are simulation-only defaults, so no
changes are required to run the project locally. To enable the AI assistant,
open `.env` and set these values for your OpenAI-compatible provider:

```dotenv
MES_AI_API_ENDPOINT=https://your-provider.example/v1/chat/completions
MES_AI_API_KEY=your-api-key
MES_AI_MODEL=your-model-name
```

Leave the optional `MES_RAG_EMBEDDING_*` values blank to use the same provider
configuration where supported. If the dashboard will be accessible from any
other computer, replace all demo passwords and `MES_DASHBOARD_SECRET` before
changing `MES_BIND_ADDRESS` from `127.0.0.1`.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) after the containers become healthy.

The included credentials are simulation-only defaults. Keep the application bound to localhost unless you replace them.

## Verify the installation

```powershell
docker compose ps
```

The SQL Server, MQTT broker, and dashboard services should report as healthy. OPC UA and MQTT certificates and the broker password file are generated automatically in Docker volumes during first startup.

Additional architecture, configuration, operations, and developer documentation is maintained locally.

## Test startup

The local test environment is optional for users who only want to run the Docker simulation.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
