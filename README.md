# Artist Art Downloader

A desktop tool that automatically finds and downloads cover art for the music artists in your local music collection. It searches Apple Music and Deezer for artist pictures, then saves them right next to your music files.

---

## What Is This?

If you have a music collection on your computer -- MP3s, FLACs, whatever -- and you like seeing album art or artist photos when you browse your files, this tool does the heavy lifting for you.

You point it at a folder full of music, and it:
- Scans all your audio files to figure out which artists you have
- Looks up each artist on Apple Music or Deezer
- Downloads the artist image and saves it to your music folder
- Works through your whole collection without you having to babysit it

It can look up images on Apple Music or Deezer. Both are free to use -- no accounts or API keys needed.

---

## How It Looks

The program opens as its own window. It has a clean, dark design that is easy on the eyes. You can also switch between a few different color themes (like a light mode, a purple Dracula look, a blue GitHub-style midnight theme, and others) in the Settings.

The main window has a folder selector at the top, a Start button, a progress bar, and a scrolling log at the bottom where you can see exactly what is happening.

---

## How To Use It (Step by Step)

**1. Pick a music service**

In the Settings menu (top-right corner), choose which service you want to search. Apple Music is the default and recommended option. Deezer is a good alternative if Apple Music does not find what you are looking for. You can switch between them anytime.

**2. Select your music folder**

Click the Browse button and pick the folder that contains your music. It can be a top-level folder (like "My Music") with all your artist subfolders inside. The program will scan everything inside it, no matter how deep the folders go.

You can also drag and drop a folder from Windows Explorer directly onto the folder bar.

If you have scanned this folder before, you can pick it from the Recent dropdown.

**3. Decide whether to skip artists that already have images**

There is a checkbox labeled "Skip artists with existing artist.jpg". If you check it, the program will skip any artist that already has an image file in their folder. This is useful if you already have covers for most of your collection and just want to fill in the gaps.

If you leave it unchecked, it will overwrite existing images with whatever it finds.

**4. Hit Start**

Click the big Start button. The program will begin scanning your music folder. You will see a progress bar moving and a live log at the bottom showing you each step:

- First it scans your files and reads the artist names from the music tags.
- Then it searches each artist one by one.
- Finally it downloads the images it found.

The log uses colors to help you read it -- green for successful downloads, red for errors, gray for skipped artists.

**5. Watch the results roll in**

As each image downloads, a small preview thumbnail appears right in the log so you can see what was saved. The downloaded images are saved as "artist.jpg" (or "Artist Name.jpg" if you prefer) in the same folder as your music files.

**6. Stopping the process**

If you need to stop mid-way, click the Stop button. The program will save its progress. Next time you open it, it will ask if you want to pick up where you left off.

There is also a Pause button if you just want to take a break without losing your place. Click Resume to continue.

---

## Things To Keep In Mind

- You need an internet connection. The program searches Apple Music and Deezer online, so it won't work offline.
- If you have a large collection (hundreds of artists), it will take a while. The program staggers its requests to avoid hitting rate limits, so it runs at a steady but careful pace. You can leave it running in the background.
- The program reads artist names from the tags inside your audio files, not from the file names. If your files do not have proper tags, the artist name might not be detected correctly.
- If an artist name contains "feat." or "ft." or "&" (like "Eminem feat. Dr. Dre"), the program will ask you which artist you actually want to search for. This happens automatically.
- Some very niche or independent artists might not have images on Apple Music or Deezer. In that case, the program will skip them and move on.
- The program minimizes to the system tray (the area near your clock) instead of the taskbar when you click the minimize button. Look for its icon there to bring it back. You can close it properly by clicking the X button and confirming.
- Downloaded images are saved as JPEG by default. You can change this to PNG in Settings, and adjust the image quality if you want smaller file sizes.
- If something goes wrong, the failed items are listed at the end. You can click "Retry Failed" to try again, or "Export Log" to save a report you can look through later.
