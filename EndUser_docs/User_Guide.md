# DocuBrowse v1.0.3 — User Guide

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Opening the App](#2-opening-the-app)
3. [Searching Your Documents](#3-searching-your-documents)
   - [Search Modes: Keyword, Semantic, Both](#search-modes-keyword-semantic-both)
   - [Phrase Search](#phrase-search)
   - [What the Results Show](#what-the-results-show)
   - [Deep Links — Finding the Passage Inside a Document](#deep-links--finding-the-passage-inside-a-document)
4. [Opening a File](#4-opening-a-file)
5. [Synopsis — AI-Generated Summaries](#5-synopsis--ai-generated-summaries)
6. [Filtering by Tag](#6-filtering-by-tag)
7. [Alphabetic Index Bar](#7-alphabetic-index-bar)
8. [Deleting a Document](#8-deleting-a-document)
9. [Settings](#9-settings)
   - [Document Directories](#document-directories)
   - [Ignored Directories](#ignored-directories)
   - [Other Settings](#other-settings)
10. [Dark and Light Mode](#10-dark-and-light-mode)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Introduction

DocuBrowse is a local document search tool that indexes the files on your machine and lets you find them through a browser-based interface. Point it at a folder full of PDFs, ebooks, Word documents, or text files and it builds a searchable index — not just by the words the documents contain, but by their meaning.

You could search for "that contract about the lease renewal" and find the right document even if those exact words never appear in the file.

**Supported file types:** PDF, DOCX, PPTX, XLSX, ODT, ODS, ODP, VSDX/VSDM, VSD/VSS/VST (legacy Visio, optional libvisio-tools for full body text), VDX (Visio 2003 XML), draw.io/diagrams.net (.drawio/.dio), PlantUML (.puml/.plantuml), Mermaid (.mmd), SGML/XML (.xml/.xhtml/.sgml/.sgm), DocBook (.docbook/.dbk), SVG, RSS/Atom/OPML feeds, reStructuredText (.rst), AsciiDoc (.adoc), LaTeX (.tex), Email (.eml), RTF (.rtf, optional striprtf for full body text), CSV / TSV, EPUB, MOBI, AZW3, HTML, TXT, Markdown, and config-ish plain text (.ini/.conf/.cfg/.log/.lst).

**Key features:**

- Three search modes: fast keyword search, AI-powered semantic search, and a hybrid that combines both.
- Click any document title to get an instant AI-written summary before you open the file.
- Filter by topic tags, browse alphabetically, or just scroll through everything.
- Everything runs on your own machine. No internet connection is required, no accounts, no cloud services.

---

## 2. Opening the App

DocuBrowse is a server that runs in the background and serves its interface to your web browser. Once the server is running, open your browser and go to:

```
http://127.0.0.1:8643
```

You can also type `localhost:8643` — both point to the same place.

The page loads with all your indexed documents displayed. A stats line in the header shows the total document and tag counts, for example: **1,842 docs · 94 tags**.

If you see a blue banner that says "No document directory configured yet," your system administrator has not yet set a document folder. Click the **Settings** (gear) icon in the header to configure one.

If you see an error saying the page cannot be reached, the DocuBrowse service is not running. Contact whoever manages your installation to start it, or see [Troubleshooting](#11-troubleshooting).

---

## 3. Searching Your Documents

The search bar is at the top of the page, centered in the header. Start typing and results appear within a fraction of a second. You do not need to press Enter.

### Search Modes: Keyword, Semantic, Both

Three buttons sit to the right of the search bar: **Keyword**, **Semantic**, and **Both**. The active mode is highlighted in blue. **Both** is selected by default.

**Keyword** — Looks for your exact words in the document title, filename, author, subject, and content. This is similar to a traditional "find in files" search. It is fast and reliable when you know a specific word or phrase that appears in the document.

Example: searching `invoice 2024` will find documents that literally contain those words.

**Semantic** — Uses an AI model to understand the meaning behind your query and finds documents that are conceptually related, even if they use completely different words. Useful when you remember what a document was about but not its exact wording.

Example: searching `payment dispute` might surface documents about billing disagreements, charge-backs, or contested invoices, even if none of them contain the phrase "payment dispute."

**Both** — The default mode. Runs both searches and combines them, weighting semantic results at 70% and keyword results at 30%. This is the recommended mode for most searches because it captures both exact matches and conceptually related documents.

### Phrase Search

In **Keyword** mode only, you can wrap a phrase in double quotes to search for that exact sequence of words.

For example, typing `"import fmt"` will find documents containing that exact phrase — useful for searching source code or technical documentation.

Phrase search does not work in Semantic or Both modes. In those modes, the quotes are ignored and DocuBrowse searches by meaning instead.

### What the Results Show

Each result is displayed as a card. A card contains:

- **Title** — The document title, displayed in blue. Click it to open a synopsis (see [Synopsis](#5-synopsis--ai-generated-summaries)).
- **Action buttons** — **Open** and/or **Download** buttons appear below the title (see [Opening a File](#4-opening-a-file) for details on which buttons appear). Next to them are icon buttons: 📋 copy link, 🔖 add tags, 🙈 hide, and ❌ remove document.
- **File path** — When accessing remotely, the full path to the file on the server is shown. Hidden in local mode since the path is not useful.
- **Snippet** — The first few lines of extracted text, giving you a preview of the content.
- **Tags** — Colored labels showing the document's topics and format. Click a tag to filter by it.
- **File type badge** — Shows the file extension (PDF, DOCX, EPUB, etc.) in the top-right corner of the card.
- **Match score** — When searching, a small badge shows the relevance score as a percentage (e.g., **87%**). Green means a strong match, orange is moderate, and grey is low.
- **Date modified** — Shown in the lower-right corner of the card.

The results bar above the cards shows how many documents matched and how long the search took: for example, `1-50 of 312 for "cloud security" 48ms`.

Use the **Back** and **Next** buttons in the results bar to page through results. You can also change how many results appear per page using the dropdown (25, 50, 75, or 100 per page).

### Deep Links — Finding the Passage Inside a Document

A search tells you *which* documents match. **Deep Links** tells you *where* inside a document the match is.

When you have an active search, each result card shows a **Deep Links** button next to **Open**. Click it and DocuBrowse looks inside that one document for the passages that match your query, then lists them — each with a short preview and a location label (**page**, **line**, or **section**). Click any passage to see it in full with the matching text highlighted in yellow, then use **Open full document** to open the file, or **Back** to return to the list.

Deep Links follows the mode of your search: a **Semantic** search finds passages by meaning, while **Keyword** (or **Both**) finds them by the words you typed. To switch, run a new search in the mode you want.

It works on text documents — **PDF, TXT, HTML, Markdown, DOCX, RTF, ODT**, e-books (EPUB, MOBI, AZW3), DjVu, and most other text and markup formats (XML, RSS/Atom, DocBook, reStructuredText, AsciiDoc, LaTeX, config files, JSON/YAML, email, and source code). (DRM-protected e-books can't be read, so those still open in their reader.) Spreadsheets, presentations, and diagrams don't display as flowing text, so for those Deep Links offers to open the file in its normal reader instead.

---

## 4. Opening a File

Each document card shows action buttons below the file path, depending on how you access DocuBrowse:

- **Local access** (browsing on the same machine as the server): An **Open** button appears. Clicking it opens the file in the application your operating system has configured for that file type — for example, a PDF opens in your PDF viewer, a DOCX opens in LibreOffice Writer or Microsoft Word.
- **Remote access** (browsing from a different machine): A **Download** button appears instead. Clicking it streams the file to your browser as a download.
- **Enterprise desktop client**: Both **Open** and **Download** buttons are available.

You can also click the **📋** icon next to the title to copy the full file path to your clipboard, so you can paste it into a terminal or file manager.

**If the file has been moved or deleted:** DocuBrowse will display a warning modal explaining that the file no longer exists. Clicking OK removes the stale entry from the index. If the file is on a drive that is currently not connected, you will see a brief notification at the bottom of the screen and the index entry is left in place.

---

## 5. Synopsis — AI-Generated Summaries

Each document card has an AI synopsis feature. Click the **document title** (the blue text at the top of the card) to open the synopsis panel.

A modal window appears with the document title and a loading message: "Generating synopsis…"

The synopsis is generated on demand by an AI model running locally on your machine. The first time you request a synopsis for a document, it may take anywhere from a few seconds to about a minute, depending on the document length and how quickly the AI model starts up. You will see reassuring messages if it takes longer than expected:

- After 6 seconds: "Still working… this can take a bit longer the first time after a restart."
- After 25 seconds: "Still generating… the AI model may still be loading into memory. Hang tight."

Once generated, the synopsis is saved. The next time you click that document's title, the synopsis appears immediately from the saved copy.

Click **Close** to dismiss the synopsis panel.

If the synopsis fails — for example because the AI service is not available — the panel will show an error message in orange. See [Troubleshooting](#11-troubleshooting) for what to do.

---

## 6. Filtering by Tag

Tags are short labels assigned to each document based on its file type, directory location, and content. They appear as small coloured chips on each document card.

To filter by a tag, you have two options:

1. **Click any tag on a document card.** This immediately searches for all documents with that tag and replaces the current results.
2. **Use the tag panel.** Click the **tags** button (with a right-arrow icon) near the top of the page, just below the header. This expands a panel showing all available tags with their document counts. Click any tag in this panel to filter.

Only tags that appear on at least three documents are shown in the tag panel.

To clear a tag filter, delete the text from the search bar or click the **Home** button in the alphabetic index bar.

### Adding Tags Manually

Click the 🔖 icon on any card to open the tag modal. Enter one or more tags separated by commas (e.g. `security, networking, reference`) and click **Add tags**. Tags are appended — existing tags on that document are not removed.

### Hiding and Unhiding Documents

Click the 🙈 icon on any card to hide it. The card fades out and is removed from the current view. Behind the scenes, this adds a "hidden" tag to the document.

Hidden documents are not deleted — they remain in the index and can be brought back at any time. To see them, click the **Show 🙈** button that appears next to the page count in the results bar. All hidden cards reappear, each showing a 👀 icon instead of 🙈 and a "hidden" tag chip.

To unhide a document, click the 👀 icon. The "hidden" tag is removed and the icon reverts to 🙈. Click **Hide 🙈** in the results bar to toggle hidden cards back out of view.

---

## 7. Alphabetic Index Bar

Below the results count, a row of letter buttons spans the full width of the page: **Home**, **0-9**, **A**, **B**, **C** … **Z**.

Click any letter to display all documents whose title starts with that letter. The results bar will show "Starting with 'B'" (for example) and you can page through them with the **Back** and **Next** buttons.

Buttons for letters that have no matching documents are shown at reduced opacity and cannot be clicked.

Click the currently active letter again to return to All Documents. Alternatively, click the **Home** button on the left end of the bar to return to All Documents from anywhere.

The index bar stays visible and functional while you are viewing search results, letter-filtered results, or the full document list.

---

## 8. Deleting a Document

Each document card has a trash icon (**🗑**) near the top-right corner of the title row. Clicking it opens a modal with four options:

1. **Remove from index only** — the file stays on disk and will be re-indexed on the next scan.
2. **Remove & blacklist** — the file stays on disk but is added to the scan blacklist so future scans skip it.
3. **Remove & delete file from disk** — permanently removes the file from both the index and the disk. A second confirmation is required before the file is deleted. This action cannot be undone.
4. **Cancel** — dismiss the modal without doing anything. You can also press Escape or click outside the dialog.

After any removal option, the document card fades out and disappears from the current view.

---

## 9. Settings

Click the **Settings** button (the gear icon) in the top-right area of the header to open the Settings page in a new browser tab.

The Settings page has two panels: **General** and **Ignored Directories**. Click **Done** in the header to save changes and return to the search tab, or click **Back to search** to return without saving.

### Document Directories

The **General** panel shows a field labelled **Document directories**. This is the list of folders that DocuBrowse scans and indexes.

To add a directory, type a path into the text field or click **Browse…** to navigate your filesystem with a directory picker. Then click **Add**. The directory is added to the list immediately.

To remove a directory, click the **✕** button to the right of its entry in the list.

Click **Save** after making changes to the directory list, working directory, or port.

A note about scanning: adding or removing a directory in Settings updates the list that DocuBrowse uses. To actually scan a newly added directory and index its documents, a rescan must be run. Your administrator can do this from the command line. Similarly, removing a directory from the list does not immediately remove those documents from the index — a rescan is needed to apply the change.

### Ignored Directories

The **Ignored Directories** panel lets you exclude specific folders from scanning. Documents already indexed from an excluded directory are removed from the index when you add it to the exclusion list.

To exclude a directory, type its path or click **Browse…** to navigate to it, then click **Add**. You will be asked to confirm before any already-indexed documents are purged.

To remove a directory from the exclusion list, click the **✕** next to it. This does not immediately re-index those documents — run a rescan to bring them back.

Currently excluded directories are shown in the **Currently excluded directories** list.

### Other Settings

The **General** panel also contains:

- **workDir** — the folder where DocuBrowse keeps its database and other files. This is set during installation and rarely needs to change.
- **port** — the HTTP port the server listens on. The default is **8643**. If you change this, the URL you use to access DocuBrowse will change to match.

---

## 10. Dark and Light Mode

DocuBrowse opens in dark mode by default. To switch, click the theme toggle button in the top-right area of the header.

In dark mode, the button shows a sun icon and is labelled **Light** — clicking it switches to light mode.

In light mode, the button shows a moon icon and is labelled **Dark** — clicking it switches back to dark mode.

Your preference is saved in the browser and restored the next time you open the page.

---

## 11. Troubleshooting

### The page says "Cannot reach the DocuBrowse service"

The DocuBrowse server is not running, or the browser cannot connect to it. Try reloading the page. If the error persists, contact whoever manages your DocuBrowse installation and ask them to start the server.

### The synopsis shows an error

This means the AI service (Ollama) is not available. The synopsis feature requires a locally running AI model. Possible causes:

- Ollama has not been started.
- The required AI model has not been downloaded yet.

Your administrator can resolve this by starting Ollama and ensuring both the `nomic-embed-text:latest` and `dolphin3:latest` models are installed.

### Clicking a file does nothing, or shows an error

DocuBrowse opens files using your operating system's default application for each file type. If clicking a PDF does nothing, your system may not have a PDF viewer configured. Your administrator can fix this by installing an appropriate application and configuring it as the default for that file type using your system's file association settings.

### Phrase search is not working

Phrase search — typing `"exact phrase"` in double quotes — only works in **Keyword** mode. If you are in **Semantic** or **Both** mode, the quotes are ignored and the search runs by meaning instead.

To use phrase search, click the **Keyword** button in the header to switch to Keyword mode, then enter your quoted phrase.

### A document appears in search results but the file is missing

If you click a file path and see a warning that the document no longer exists on disk, the file has been moved, renamed, or deleted since DocuBrowse last indexed it. Click **OK** in the warning dialog to remove the stale entry from the index.

If this happens for many documents at once (for example, after reorganising a folder), ask your administrator to run the `scan-missing` maintenance command, which cleans up the whole index in one pass.

### Semantic search returns no results

Semantic search requires embeddings to be generated for your documents. If your index was recently built or the embedding step was skipped, some or all documents may not have embeddings yet.

Ask your administrator to run the `embed` command to generate embeddings for any documents that are missing them.

### Search results seem out of date

DocuBrowse does not watch for file changes continuously. The index reflects the last time a scan was run. If you have added new documents and they do not appear in search results, ask your administrator to run a rescan.
