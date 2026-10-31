# Data files

Ask Arelis about a CSV, TSV, JSON, Excel, or FITS file and it reads the file from your workspace folder. Put the file in that folder, then ask by name, for example "what is the average in readings.csv?".

Arelis runs a short piece of Python on the file in a separate process. Charts and tables it makes are saved in the `results` folder inside your workspace folder. It never reads files outside that folder and never writes anywhere but `results`.

If you switch projects, Arelis reads from the folder of the project that is open. Saved jobs that run while you are away do not use this tool.
