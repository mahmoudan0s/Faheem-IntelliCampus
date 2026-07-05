# "Faheem" / IntelliCampus Academic Advisor

A RAG (Retrieval-Augmented Generation) AI academic advisor for university students. It combines vector search over academic regulations (pgvector), student data from SQL Server, and LLM reasoning to answer questions about registration, GPA, graduation, etc. It also has a course materials RAG feature for uploading PDFs/images, chunking, embedding, and Q&A over course content, Smart notes Enhance student notes with course material and summarize lectures with a suggestion for sources.

## Requirements

- Python 3.8 or later

#### Install Python using MiniConda

1) Download and install MiniConda from [here](https://docs.anaconda.com/free/miniconda/#quick-command-line-install)
2) Create a new environment using the following command:
```bash
$ conda create -n mini-rag python=3.8
```
3) Activate the environment:
```bash
$ conda activate mini-rag
```

### (Optional) Setup you command line interface for better readability

```bash
export PS1="\[\033[01;32m\]\u@\h:\w\n\[\033[00m\]\$ "
```

## Installation

### Install the required packages

```bash
$ pip install -r requirements.txt
```
##Run Docker Compose Services
```bash
$ cd docker
$ cp .env.example .env
```
```bash
update .env with your credentials
$ cd docker
$ sudo docker compose up -d
```
### Setup the environment variables

```bash
$ cp .env.example .env
```
Set your environment variables in the `.env` file. Like `OPENAI_API_KEY` value.

## Run the fast api server
'''bash
uvicorn main:app --reload --host 0.0.0.0 --port 5000
'''


### POSTMAN collection
'''
