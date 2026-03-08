# Book Translator

Translate books (EPUB and PDF) from English to any language using Claude's API with intelligent caching and context management.

## Features

- **Multi-format support**: Translate both EPUB and PDF files
- **Smart caching**: MongoDB-backed translation cache to avoid re-translating identical content
- **Context awareness**: Maintains character names, place names, and chapter summaries for consistency
- **Literary quality**: Language-specific translation instructions, with built-in support for Spanish literary conventions
- **Cost tracking**: Estimates API costs for each translation
- **Glossary generation**: Automatically creates a glossary of character and place name translations
- **Batch processing**: Handles multi-page documents efficiently

## Requirements

- Python 3.8+
- MongoDB (optional, for caching)
- Anthropic API key

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/book-translator.git
cd book-translator
```

2. Create a virtual environment:
```bash
python -m venv .venv
```

3. Activate the virtual environment:
   - **Windows (PowerShell)**:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS/Linux**:
     ```bash
     source .venv/bin/activate
     ```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

5. Set up your API key:
   - **Windows (PowerShell)**:
     ```powershell
     $env:ANTHROPIC_API_KEY = 'your-api-key-here'
     ```
   - **macOS/Linux**:
     ```bash
     export ANTHROPIC_API_KEY='your-api-key-here'
     ```

## MongoDB Setup (Optional)

For translation caching:

```bash
# Using Docker (recommended)
docker run -d -p 27017:27017 --name mongodb mongo:latest

# Or install locally: https://www.mongodb.com/try/download/community
```

If MongoDB is not available, the tool will work without caching.

## Usage

### Translate a PDF:
```bash
python main.py input.pdf output_translated.pdf Spanish
```

### Translate an EPUB:
```bash
python main.py input.epub output_translated.epub German
```

### Supported Languages:
Spanish, German, French, Italian, Portuguese, Japanese, Chinese, and any language supported by Claude.

## How It Works

1. **File Parsing**: Extracts text content while preserving structure
2. **Context Building**: Creates context from previous chapters and maintains a glossary
3. **Translation**: Sends text chunks to Claude Sonnet with literary style instructions
4. **Caching**: Stores translations in MongoDB to avoid redundant API calls
5. **Formatting**: Rebuilds the document with translated content
6. **Output**: Generates translated PDF/EPUB and glossary file

## API Costs

Estimated costs depend on:
- Claude Sonnet 4.5: ~$0.003 per 1K input tokens, ~$0.015 per 1K output tokens
- Typical book (100K words): $15-25 USD

Costs are displayed at the end of each translation.

## Output Files

After translation, you'll get:
- `output_translated.pdf` or `output_translated.epub` - The translated book
- `output_translated_glossary.txt` - Character and place name translations for reference

## Configuration

Edit `BookTranslator` initialization in `main.py` to customize:
- `target_language`: Change the target language
- `use_cache`: Enable/disable MongoDB caching
- `mongo_uri`: Custom MongoDB connection string

## Performance

- **First translation**: Full API usage, translations cached
- **Subsequent translations**: Cached hits reduce API costs significantly
- **Large documents**: Processed in chunks for memory efficiency
- **Spanish mode**: Includes RAE-compliant formatting (em dashes, inverted punctuation)

## Limitations

- Text extraction depends on PDF/EPUB quality; scanned images not supported
- Very long chapters may be split into multiple API calls
- Complex document layouts may not preserve perfectly
- Maximum token limit per request: 8,192 tokens

## License

MIT License - see LICENSE file for details

## Disclaimer

This tool is provided for educational and personal use only. Users are solely responsible for:

- Ensuring they have legal rights to translate and modify any books or documents processed with this software
- Complying with applicable copyright laws and intellectual property regulations
- Obtaining necessary permissions from copyright holders before translating copyrighted material
- Using translations only for permitted purposes (personal use, fair use, etc.)

The creator and maintainers of this software are not responsible for:

- Copyright infringement or intellectual property violations by users
- Unauthorized use or distribution of translated content
- Any legal consequences resulting from the use of this software
- The accuracy or quality of translations produced
- Data loss or system damage caused by this software

Users must not use this tool to infringe upon copyrighted works or violate any applicable laws. By using this software, you acknowledge that you understand and accept full legal responsibility for your actions.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues.

## Support

For issues or questions:
- Check that your API key is set correctly
- Verify MongoDB is running (if using caching)
- Ensure input files are readable text-based PDFs/EPUBs
