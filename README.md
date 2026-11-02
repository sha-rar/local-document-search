# Local Document Search

Search inside the documents on your computer, not just their file names.

**FileLens** (a working name) is a desktop app that reads the text of your documents once, then lets you find any word or phrase in them in a fraction of a second. Everything stays on your computer: there's no account, no cloud service, and nothing is uploaded anywhere.

> **Status:** early development. The app works, but there's no installer yet, so you'll need Python to set it up (instructions below). It has been developed and tested on Windows 11.

## What it can do

- **Search the contents of your files.** Type a word or phrase and see every document that contains it, best matches first.
- **Preview before opening.** Each result shows where it is, when it was last changed, and an excerpt with your search terms highlighted.
- **Open files directly.** Double-click a result to open it, or jump to it in File Explorer.
- **Stay up to date on its own.** While the app is open, it notices files you add, edit, move or delete and updates its results.
- **Leave things out.** Skip private folders, particular file types, or names like `~$*` temporary files.

### Supported files

| Type | Notes |
|---|---|
| Text (`.txt`) and Markdown (`.md`) | |
| PDF (`.pdf`) | Only PDFs that contain real text. Scanned pages (images of text) can't be searched yet. |
| Word (`.docx`) | Older `.doc` files aren't supported. |

Password-protected files are skipped and listed so you know which ones were missed.

## Installing

You'll need [Python 3.11 or newer](https://www.python.org/downloads/). When installing Python on Windows, tick **"Add python.exe to PATH"**.

Open PowerShell and run:

```powershell
git clone https://github.com/sha-rar/local-document-search.git
cd local-document-search
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[gui]"
```

No Git? Use the green **Code → Download ZIP** button on GitHub, unzip it, open PowerShell in that folder, and run the last three commands.

## Starting the app

From the project folder in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
filelens
```

The first line activates the app's environment, which you need to do each time you open a new PowerShell window.

## Using it

1. **Add folders.** Click **Add folder…** and choose a folder, such as `Documents`. Subfolders are included automatically. Add as many folders as you like.
2. **Index them.** Click **Index now**. The app reads each document and builds its search index. A progress bar shows how far along it is, and you can **Pause** or **Cancel** at any time without losing the work already done.
3. **Search.** Type in the search box. Results appear as you type. Use the drop-down next to the search box to show only one file type.
4. **Look and open.** Click a result to preview it on the right. Double-click it, or click **Open**, to open the file in its usual app. **Show in folder** opens File Explorer with the file selected.

Your folders and settings are remembered, so next time you only need to start the app and search.

### Search tips

| You type | You get |
|---|---|
| `budget forecast` | Documents containing **both** words, anywhere in the text |
| `"quarterly review"` | Documents containing that **exact phrase** |
| `budget "quarterly review"` | Both of the above at once |

- Capital letters and accents don't matter: `cafe` finds `Café`.
- Words must match exactly: `plan` won't find `planning`.
- File names are searched too, and a match in the name ranks higher.

### How long does indexing take?

The **first** index of a large folder can take a few minutes, especially with lots of PDFs, or the first time your antivirus checks each file. After that, the app only re-reads files that have changed, so keeping it up to date takes seconds.

If something couldn't be read, a **problems…** button appears at the bottom of the window. Click it to see which files were skipped and why.

### Settings

Open **File → Settings…** to:

- **Exclude folders**, such as a private subfolder inside `Documents`.
- **Skip files by name**, using `*` as a wildcard. By default the app skips `~$*` (temporary files Word creates while a document is open), `.git` and `node_modules`.
- **Choose which file types to index.**
- **Set the maximum number of results** shown for each search.
- **Choose when the index updates**: automatically while the app is open (on by default), and/or each time the app starts.

## Your data and privacy

The app never sends anything over the internet. It keeps three things on your computer, in `%LOCALAPPDATA%\FileLens` (usually `C:\Users\<you>\AppData\Local\FileLens`):

- **The search index** (`index.db`). This contains a copy of the text from every indexed document, so treat it as being as private as the documents themselves.
- **Your settings** (`settings.json`).
- **A log file** (`logs\filelens.log`). This records what the app did, to help track down problems: which folders were indexed, the names and locations of files that couldn't be read, and the text of any search that failed. It doesn't record what's written inside your documents, and old entries are discarded once the log reaches a few megabytes.

To start over, close the app and delete that folder. Your actual documents are never changed, moved or deleted.

## Command-line version

If you prefer the terminal, the same features are available through the `docsearch` command. It uses the same index as the app.

```powershell
docsearch index C:\Users\you\Documents          # index a folder
docsearch search "quarterly review"             # search
docsearch search budget --type pdf --after 2025-01-01
docsearch prune                                 # forget files that no longer exist
docsearch --help                                # all options
```

## Troubleshooting

**"running scripts is disabled on this system" when activating.** Run this once, then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**`filelens` isn't recognised.** Activate the environment first with `.\.venv\Scripts\Activate.ps1`, from inside the project folder. You can also start the app with `python -m local_document_search.gui`.

**A document I expected doesn't show up.** Check that:
- its folder has been added and indexed,
- it isn't excluded in **File → Settings…**,
- it's a supported type, and
- it isn't listed under **problems…**. Scanned PDFs and password-protected files can't be searched.

**Results still show a file I deleted.** Click **Index now** to refresh. If the file lived in a folder you no longer index, run `docsearch prune`.
