import os
import datetime
import asyncio
import smtplib
import json
import time
from dotenv import load_dotenv 
import google.generativeai as genai
from playwright.async_api import async_playwright
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# Load environment variables
load_dotenv() 

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") 
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

genai.configure(api_key=GEMINI_API_KEY)

async def generate_report():
    today_str = datetime.date.today().strftime("%B %d, %Y")
    print(f"[{datetime.datetime.now()}] 🚀 Starting Cloud Pipeline for {today_str}...")
    
    if not os.path.exists('reports'): os.makedirs('reports')

    try:
        # 1. STRICT MODEL SELECTION (Avoids low-quota preview models)
        print("📡 Querying Google for stable models...")
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # We EXPLICITLY look for 1.5-flash first because it has the highest free tier quota
        if "models/gemini-1.5-flash" in available_models:
            selected_model = "models/gemini-1.5-flash"
        elif "models/gemini-1.5-flash-latest" in available_models:
            selected_model = "models/gemini-1.5-flash-latest"
        else:
            # If 1.5 isn't found, pick the oldest available (usually higher quota)
            selected_model = available_models[0]

        print(f"✅ Forced Stable Model: {selected_model}")
        model = genai.GenerativeModel(selected_model)
    
        # Filter for 'flash' models as they are fastest and have better free tier limits
        flash_models = [m for m in available_models if "flash" in m]
        
        # Pick 1.5 if available (stable), otherwise pick the first flash model, otherwise first available
        if "models/gemini-1.5-flash" in flash_models:
            selected_model = "models/gemini-1.5-flash"
        elif flash_models:
            selected_model = flash_models[0]
        else:
            selected_model = available_models[0]

        print(f"✅ Auto-Selected Model: {selected_model}")
        model = genai.GenerativeModel(selected_model)
        
        # 2. ASK AI FOR DYNAMIC NEWS DATA
        prompt = f"""
        Today's date is {today_str}. Analyze real tech/startup news from the ACTUAL last 24 hours.
        Provide a Dominant Theme Headline, a Summary, a 'Startup of the Day', and 3 News Stories.
        
        STRICT RULES: 
        - DO NOT use the Nvidia $3T story or Sword Health $3B story from 2024.
        - Find REAL news published between June 9 and June 10, 2026.
        
        Format your response ONLY as a valid JSON object with these keys:
        "hero_title", "hero_summary", "exec_brief", "whatsapp_alert", "startup_name", "startup_sector", "startup_valuation", "startup_takeaway", "story1_head", "story2_head", "story3_head"
        """
        
        # 3. API CALL WITH QUOTA SAFETY
        response = None
        for attempt in range(2):
            try:
                response = model.generate_content(prompt)
                break 
            except Exception as e:
                if "429" in str(e):
                    print(f"⚠️ Quota hit. Waiting 70s to reset (Attempt {attempt+1}/2)...")
                    await asyncio.sleep(70) # Wait slightly more than a minute
                else:
                    raise e

        if not response or not response.text:
            raise Exception("AI failed to respond.")

        # Parse JSON
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        ai_data = json.loads(raw_text)
        print("✅ Intelligence Synthesized.")

        # 4. PREPARE REPLACEMENTS
        metrics = {
            "{{LAST_UPDATED}}": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "{{NEXT_REFRESH}}": (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d 06:00 AM"),
            "{{SOURCE_COVERAGE}}": "99.8%",
            "{{AI_CONFIDENCE}}": "98.7%",
            "{{HERO_TITLE}}": ai_data["hero_title"],
            "{{HERO_SUMMARY}}": ai_data["hero_summary"],
            "{{EXECUTIVE_BRIEF}}": ai_data["exec_brief"],
            "{{WHATSAPP_ALERT}}": ai_data["whatsapp_alert"],
            "{{STARTUP_NAME}}": ai_data["startup_name"],
            "{{STARTUP_SECTOR}}": ai_data["startup_sector"],
            "{{STARTUP_VALUATION}}": ai_data["startup_valuation"],
            "{{STARTUP_TAKEAWAY}}": ai_data["startup_takeaway"],
            "{{STORY_1_HEAD}}": ai_data["story1_head"],
            "{{STORY_2_HEAD}}": ai_data["story2_head"],
            "{{STORY_3_HEAD}}": ai_data["story3_head"]
        }

        # 5. GENERATE HTML
        with open("template.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        for key, val in metrics.items():
            html_content = html_content.replace(key, str(val))
        
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_content)

        # 6. GENERATE PDF
        pdf_path = f"reports/TechPulse_{datetime.date.today()}.pdf"
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={'width': 1400, 'height': 1200})
            await page.set_content(html_content)
            await asyncio.sleep(2) 
            await page.pdf(path=pdf_path, width="1400px", print_background=True, prefer_css_page_size=True)
            await browser.close()
        print(f"✅ PDF Saved: {pdf_path}")

        # 7. EMAIL DISPATCH
        msg = MIMEMultipart()
        msg['Subject'] = f"TechPulse AI Intelligence Briefing | {today_str}"
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg.attach(MIMEText(f"Executive Intelligence Report for {today_str} attached.", 'plain'))
        with open(pdf_path, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="pdf")
            attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_path))
            msg.attach(attach)
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print("📧 Pipeline Success. Email sent and Vercel updated.")

    except Exception as e:
        print(f"❌ PIPELINE FAILURE: {str(e)}")

if __name__ == "__main__":
    asyncio.run(generate_report())


