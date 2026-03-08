#!/usr/bin/env python3
"""
Book Translator - EPUB and PDF Support
Translates books using Claude API with context management.
"""

import anthropic
from ebooklib import epub
from bs4 import BeautifulSoup
import os
from typing import List, Dict, Optional
import re
import hashlib
from pymongo import MongoClient
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY


class BookTranslator:
    def __init__(self, api_key: str, target_language: str = "Spanish", use_cache: bool = True, mongo_uri: str = "mongodb://localhost:27017/"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.target_language = target_language
        self.glossary: Dict[str, str] = {}  # Track character names, places
        self.chapter_summaries: List[str] = []
        self.use_cache = use_cache
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Initialize MongoDB cache
        if use_cache:
            try:
                self.mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                self.db = self.mongo_client['book_translator']
                self.cache = self.db['translations']
                # Create index on hash for faster lookups
                self.cache.create_index('text_hash')
                print("✅ MongoDB cache connected")
            except Exception as e:
                print(f"⚠️  MongoDB not available, caching disabled: {e}")
                self.use_cache = False
        
    def _get_text_hash(self, text: str, target_lang: str) -> str:
        """Generate hash for cache key"""
        content = f"{text}|{target_lang}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def get_from_cache(self, text: str) -> Optional[Dict[str, str]]:
        """Retrieve translation from cache"""
        if not self.use_cache:
            return None
        
        text_hash = self._get_text_hash(text, self.target_language)
        try:
            cached = self.cache.find_one({'text_hash': text_hash})
            if cached:
                self.cache_hits += 1
                return {
                    'translation': cached['translation'],
                    'summary': cached.get('summary', '')
                }
            self.cache_misses += 1
        except Exception as e:
            print(f"⚠️  Cache read error: {e}")
        return None
    
    def save_to_cache(self, text: str, translation: str, summary: str = ""):
        """Save translation to cache"""
        if not self.use_cache:
            return
        
        text_hash = self._get_text_hash(text, self.target_language)
        try:
            self.cache.update_one(
                {'text_hash': text_hash},
                {'$set': {
                    'text_hash': text_hash,
                    'source_lang': 'English',
                    'target_lang': self.target_language,
                    'translation': translation,
                    'summary': summary,
                    'text_preview': text[:200]  # Store preview for debugging
                }},
                upsert=True
            )
        except Exception as e:
            print(f"⚠️  Cache write error: {e}")
    
    def extract_text_from_html(self, html_content: bytes) -> tuple[str, BeautifulSoup]:
        """Extract text while preserving structure"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = soup.get_text(separator='\n', strip=True)
        return text, soup
    
    def build_context(self, chapter_num: int) -> str:
        """Build context from previous chapters"""
        context_parts = []
        
        if self.glossary:
            context_parts.append("Character/Place Names (maintain consistency):")
            context_parts.append("\n".join([f"- {k}: {v}" for k, v in list(self.glossary.items())[:10]]))
        
        if self.chapter_summaries and chapter_num > 0:
            context_parts.append("\nPrevious chapter summary:")
            context_parts.append(self.chapter_summaries[-1])
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def translate_chunk(self, text: str, chapter_num: int, chapter_title: str = "") -> tuple[str, str]:
        """Translate a text chunk with context"""
        
        # Check cache first
        cached = self.get_from_cache(text)
        if cached:
            print("   💾 Using cached translation")
            return cached['translation'], cached['summary']
        
        context = self.build_context(chapter_num)
        
        # Spanish-specific literary instructions
        spanish_style = ""
        if self.target_language.lower() in ['spanish', 'español', 'castellano']:
            spanish_style = """
6. Use professional Spanish literary conventions:
   - Use em dashes (—) for dialogue, NOT quotation marks (e.g., —Hola —dijo él.)
   - Use em dashes (—) for interruptions and asides instead of commas or parentheses
   - Follow RAE (Real Academia Española) standards
   - Use inverted question marks (¿?) and exclamation marks (¡!)
   - Employ rich, literary vocabulary appropriate for published literature
   - Maintain formal narrative voice typical of Spanish literary prose
   - Use subjunctive mood appropriately
   - Prefer compound sentences with varied syntax over simple structures"""
        
        prompt = f"""This translation is for personal, non-commercial use only and will not be distributed.

Translate the following text from English to {self.target_language}.

{f'Context from previous chapters:{chr(10)}{context}{chr(10)}{chr(10)}' if context else ''}

Instructions:
1. Maintain literary style and tone
2. Keep character names consistent with the glossary
3. Preserve paragraph structure
4. Keep any formatting markers (like italics indicators)
5. Be natural and readable in {self.target_language}
6. CRITICAL: Do NOT translate "###PAGE_BREAK###" - preserve it EXACTLY as written{spanish_style}
7. If you see chapter titles or headings, translate them normally but do NOT add extra copies

Text to translate:

{text}

Provide ONLY the translation, no explanations or notes."""

        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8192, 
            temperature=0.3,  # Lower temperature for consistency
            messages=[{"role": "user", "content": prompt}]
        )
        
        translation = response.content[0].text
        
        # Extract summary for next chapter's context
        summary_prompt = f"In 2-3 sentences, summarize the key events in this chapter:\n\n{text[:1000]}"
        summary_response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # Use Haiku for summaries (cheaper)
            max_tokens=150,
            messages=[{"role": "user", "content": summary_prompt}]
        )
        summary = summary_response.content[0].text
        
        # Save to cache
        self.save_to_cache(text, translation, summary)
        
        return translation, summary
    
    def update_glossary(self, original_text: str, translated_text: str):
        """Extract and update character/place names"""
        # Simple extraction of capitalized words (names)
        original_names = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', original_text))
        translated_names = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', translated_text))
        
        # Match them up (simplified, could be smarter)
        for orig, trans in zip(sorted(original_names)[:5], sorted(translated_names)[:5]):
            if orig not in self.glossary:
                self.glossary[orig] = trans
    
    def translate_epub(self, input_path: str, output_path: str):
        """Main translation function"""
        print(f"📚 Loading EPUB: {input_path}")
        book = epub.read_epub(input_path)
        
        # Debug: Show ALL items in the EPUB
        print(f"\n🔍 Analyzing EPUB structure...")
        all_items = list(book.get_items())
        print(f"Total items found: {len(all_items)}")
        for i, item in enumerate(all_items[:20]):  # Show first 20
            print(f"  {i+1}. Type: {item.get_type()}, Name: {item.get_name()}")
        print()
        
        # Get all document items (chapters)
        chapters = [item for item in book.get_items() if item.get_type() == 9]  # ITEM_DOCUMENT
        
        print(f"📖 Found {len(chapters)} DOCUMENT type items")
        print(f"🌍 Target language: {self.target_language}")
        print(f"{'='*50}\n")
        
        total_cost = 0
        
        for idx, item in enumerate(chapters):
            content = item.get_content()
            
            # Debug: Show raw HTML
            print(f"📄 Section {idx + 1}")
            print(f"   File: {item.get_name()}")
            print(f"   Raw HTML (first 1000 chars):")
            print(content[:1000].decode('utf-8', errors='ignore'))
            print()
            
            original_text, soup = self.extract_text_from_html(content)
            
            # Debug: show what we found
            print(f"   Extracted text length: {len(original_text.strip())} characters")
            print(f"   Preview: {original_text[:200]}...")
            print()
            
            # Skip if very short (likely TOC or blank page)
            if len(original_text.strip()) < 100:
                print(f"⏭️  Skipping short section {idx + 1}")
                continue
            
            # Get chapter title if available
            title_tag = soup.find(['h1', 'h2', 'h3'])
            chapter_title = title_tag.get_text() if title_tag else f"Chapter {idx + 1}"
            
            print(f"🔄 Translating: {chapter_title}")
            print(f"   Length: {len(original_text)} chars, ~{len(original_text.split())} words")
            
            # Translate
            try:
                translated_text, summary = self.translate_chunk(
                    original_text, 
                    idx, 
                    chapter_title
                )
                
                # Update glossary with this chapter's names
                self.update_glossary(original_text, translated_text)
                
                # Store summary for next chapter
                self.chapter_summaries.append(summary)
                
                # Update the HTML content
                # Replace text in the body while preserving structure
                body = soup.find('body')
                if body:
                    # Simple replacement - preserve basic HTML structure
                    paragraphs = translated_text.split('\n\n')
                    new_html = ''.join([f'<p>{p}</p>' for p in paragraphs if p.strip()])
                    body.clear()
                    body.append(BeautifulSoup(new_html, 'html.parser'))
                
                item.set_content(str(soup).encode('utf-8'))
                
                # Rough cost estimate (input + output tokens)
                input_tokens = len(original_text) / 4  # rough estimate
                output_tokens = len(translated_text) / 4
                chapter_cost = (input_tokens * 0.003 + output_tokens * 0.015) / 1000
                total_cost += chapter_cost
                
                print(f"   ✅ Done! (~${chapter_cost:.3f})")
                print(f"   📝 Glossary: {len(self.glossary)} entries")
                print()
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                continue
        
        # Write the translated EPUB
        print(f"{'='*50}")
        print(f"💾 Saving translated EPUB: {output_path}")
        epub.write_epub(output_path, book)
        
        print(f"\n✨ Translation complete!")
        print(f"💰 Estimated cost: ${total_cost:.2f}")
        print(f"📚 Glossary entries: {len(self.glossary)}")
        print(f"📖 Chapters processed: {len(self.chapter_summaries)}")
        
        # Save glossary for reference
        glossary_path = output_path.replace('.epub', '_glossary.txt')
        with open(glossary_path, 'w', encoding='utf-8') as f:
            f.write("Translation Glossary\n")
            f.write("="*50 + "\n\n")
            for orig, trans in sorted(self.glossary.items()):
                f.write(f"{orig} → {trans}\n")
        print(f"📝 Glossary saved to: {glossary_path}")
    
    def extract_text_from_pdf(self, pdf_path: str) -> List[Dict[str, str]]:
        """Extract text from PDF pages"""
        print(f"📚 Loading PDF: {pdf_path}")
        reader = PdfReader(pdf_path)
        
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text.strip():
                pages.append({
                    'number': i + 1,
                    'text': text.strip()
                })
        
        return pages
    
    def translate_pdf(self, input_path: str, output_path: str):
        """Translate a PDF file"""
        pages = self.extract_text_from_pdf(input_path)
        
        print(f"📖 Found {len(pages)} pages with text")
        print(f"🌍 Target language: {self.target_language}")
        print(f"{'='*50}\n")
        
        translated_pages = []
        total_cost = 0
        
        # Process pages in chunks (combine a few pages per translation for better context)
        chunk_size = 2  # Translate 2 pages at a time for better quality
        
        for i in range(0, len(pages), chunk_size):
            chunk_pages = pages[i:i + chunk_size]
            page_nums = [p['number'] for p in chunk_pages]
            combined_text = "\n\n###PAGE_BREAK###\n\n".join([p['text'] for p in chunk_pages])
            
            print(f"🔄 Translating pages {page_nums[0]}-{page_nums[-1]}")
            print(f"   Length: {len(combined_text)} chars, ~{len(combined_text.split())} words")
            
            try:
                chapter_title = f"Pages {page_nums[0]}-{page_nums[-1]}"
                translated_text, summary = self.translate_chunk(
                    combined_text,
                    i // chunk_size,
                    chapter_title
                )
                
                # Update glossary
                self.update_glossary(combined_text, translated_text)
                self.chapter_summaries.append(summary)
                
                # Clean up any mistranslated page breaks
                translated_text = translated_text.replace("--- Salto de página ---", "###PAGE_BREAK###")
                translated_text = translated_text.replace("--- Salto de Página ---", "###PAGE_BREAK###")
                translated_text = translated_text.replace("###SALTO_DE_PÁGINA###", "###PAGE_BREAK###")
                
                # Split back into pages
                translated_page_texts = translated_text.split("###PAGE_BREAK###")
                for j, page_text in enumerate(translated_page_texts):
                    if j < len(chunk_pages):
                        translated_pages.append({
                            'number': chunk_pages[j]['number'],
                            'text': page_text.strip()
                        })
                
                # Cost estimate
                input_tokens = len(combined_text) / 4
                output_tokens = len(translated_text) / 4
                chunk_cost = (input_tokens * 0.003 + output_tokens * 0.015) / 1000
                total_cost += chunk_cost
                
                print(f"   ✅ Done! (~${chunk_cost:.3f})")
                print(f"   📝 Glossary: {len(self.glossary)} entries\n")
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                # Add original text as fallback
                for page in chunk_pages:
                    translated_pages.append(page)
                continue
        
        # Create translated PDF
        print(f"{'='*50}")
        print(f"💾 Creating translated PDF: {output_path}")
        self.create_pdf(translated_pages, output_path)
        
        print(f"\n✨ Translation complete!")
        print(f"💰 Estimated cost: ${total_cost:.2f}")
        print(f"📚 Glossary entries: {len(self.glossary)}")
        print(f"📖 Pages processed: {len(translated_pages)}")
        
        # Cache statistics
        if self.use_cache:
            total_requests = self.cache_hits + self.cache_misses
            if total_requests > 0:
                hit_rate = (self.cache_hits / total_requests) * 100
                print(f"💾 Cache: {self.cache_hits} hits, {self.cache_misses} misses ({hit_rate:.1f}% hit rate)")
        
        # Save glossary
        glossary_path = output_path.replace('.pdf', '_glossary.txt')
        with open(glossary_path, 'w', encoding='utf-8') as f:
            f.write("Translation Glossary\n")
            f.write("="*50 + "\n\n")
            for orig, trans in sorted(self.glossary.items()):
                f.write(f"{orig} → {trans}\n")
        print(f"📝 Glossary saved to: {glossary_path}")
    
    def create_pdf(self, pages: List[Dict[str, str]], output_path: str):
        """Create a PDF from translated pages"""
        doc = SimpleDocTemplate(output_path, pagesize=letter,
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=18)
        
        story = []
        styles = getSampleStyleSheet()
        
        # Create custom style for book text
        book_style = ParagraphStyle(
            'BookText',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=12,
        )
        
        for page in pages:
            # Add page text - split into paragraphs
            paragraphs = page['text'].split('\n\n')
            for para in paragraphs:
                if para.strip():
                    # Escape special characters for reportlab
                    para_text = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(para_text, book_style))
            
            # Add extra space between original pages (subtle page break)
            story.append(Spacer(1, 0.3*inch))
        
        doc.build(story)


def main():
    """CLI interface"""
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python main.py input.[epub|pdf] output.[epub|pdf] [language]")
        print("\nExamples:")
        print("  python main.py book.pdf book_es.pdf Spanish")
        print("  python main.py book.epub book_de.epub German")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    target_lang = sys.argv[3] if len(sys.argv) > 3 else "Spanish"
    
    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ Error: ANTHROPIC_API_KEY environment variable not set")
        print("\nSet it with (PowerShell):")
        print("  $env:ANTHROPIC_API_KEY = 'your-api-key-here'")
        sys.exit(1)
    
    if not os.path.exists(input_file):
        print(f"❌ Error: Input file not found: {input_file}")
        sys.exit(1)
    
    # Create translator
    translator = BookTranslator(api_key, target_lang)
    
    # Detect file type and translate
    if input_file.lower().endswith('.pdf'):
        translator.translate_pdf(input_file, output_file)
    elif input_file.lower().endswith('.epub'):
        translator.translate_epub(input_file, output_file)
    else:
        print("❌ Error: Unsupported file format. Use .pdf or .epub")
        sys.exit(1)


if __name__ == "__main__":
    main()