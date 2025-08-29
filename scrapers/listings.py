import asyncio, random, re, os
from playwright_stealth import Stealth
from playwright.async_api import async_playwright

from config import config_input
from utils import accounts_loader, fingerprint_loader, proxies_loader, helper
# from .applications import extract_full_details

import logging
logger = logging.getLogger("spider")  # use shared logger

processed_jobs_id = helper.load_processed_jobs_id()
processed_new_company_jobs = []


async def _listing(context, job_page_url):
    page = None
    try:
        # Create new page
        page = await context.new_page()

        # Navigate to jobs page
        try:
            await page.goto(job_page_url, timeout=60000)
        except Exception:
            try:
                logger.warning(f"Retry loading page: {job_page_url}")
                await page.goto(job_page_url, timeout=60000)
            except Exception as e:
                logger.info(f"Page not loaded with twice tries. \n {job_page_url}")
                await helper.save_failed_url(job_page_url)

        # Temporary save extracted data
        list_of_processed_jobs = []
        list_of_titles = []
        list_of_companies = []
        list_of_links = []
        pagination_number = 1

        while True:
            await asyncio.sleep(config_input.RANDOM_SLEEP)

            # --- Focus page like a real user ---
            await page.bring_to_front()
            await page.locator("body").foucs()

            # Focus first job title (helps lazy load)
            await helper.simulate_human_behavior(page)

            # Simulate natural scroll (touchpad-like)
            # Move mouse into left job list before scrolling
            job_list = page.locator("div.scaffold-layout__list > div")
            await job_list.first.hover()
            await job_list.first.click() 
            # Simulate natural scroll (touchpad-like)
            for _ in range(50):
                await page.mouse.wheel(0, 40)
                await asyncio.sleep(0.03)

            try:
                # CORRECTED SELECTORS - using different selectors for different elements
                titles_locator = page.locator("//a[contains(@class,'job-card-container__link')]")
                companies_locator = page.locator("//div[contains(@class,'job-card-container')]//div[contains(@class,'artdeco-entity-lockup__subtitle')]")
                links_locator = page.locator("//div[contains(@class,'job-card-container')]//a[contains(@class,'job-card-container__link')]")

                # Get counts first
                titles_count = await titles_locator.count()
                companies_count = await companies_locator.count()
                links_count = await links_locator.count()

                logger.info(f"Found {titles_count} titles, {companies_count} companies, {links_count} links")
    

                # Extract text content
                titles = []
                companies = []
                links = []

                # Extract titles
                for i in range(titles_count):
                    try:
                        title_text = await titles_locator.nth(i).inner_text()
                        # Keep only the first unique line
                        title_text = title_text.split("\n")[0].strip()
                        titles.append(title_text)
                    except Exception as e:
                        logger.warning(f"Failed to extract title {i}: {e}")
                        titles.append("")

                # Extract companies
                for i in range(companies_count):
                    try:
                        company_text = await companies_locator.nth(i).inner_text()
                        companies.append(company_text.strip())
                    except Exception as e:
                        logger.warning(f"Failed to extract company {i}: {e}")
                        companies.append("")

                # Extract links
                for i in range(links_count):
                    try:
                        link = await links_locator.nth(i).get_attribute("href")
                        if link and not link.startswith('http'):
                            link = f"https://www.linkedin.com{link}"
                        links.append(link)
                    except Exception as e:
                        logger.warning(f"Failed to extract link {i}: {e}")
                        links.append("")

                # logger.info(f"Titles: \n{titles} companies: \n {companies} links:{links}")
            except Exception as e:
                logger.error(f"Unexpected scraping issue: {e}")
                titles, companies, links = [], [], []

            # Process collected jobs
            for title, company, link in zip(titles, companies, links):
                list_of_processed_jobs.append(link)
                job_id = await helper.get_job_id(link)
                if not job_id:
                    continue

                count = processed_new_company_jobs.count(company)

                if (
                    count > config_input.PER_COMPANY_JOBS
                    or job_id in processed_jobs_id
                    or company in config_input.ignore_companies
                ):
                    continue

                processed_jobs_id.add(job_id)
                processed_new_company_jobs.append(company)
                list_of_titles.append(title)
                list_of_companies.append(company)
                list_of_links.append(link)

                if len(list_of_titles) % 5 == 0:
                    logger.info(f"Collected {len(list_of_titles)} jobs...")

                if len(list_of_titles) >= config_input.PROCESS_BATCH_SIZE:
                    logger.info("Processing batch...")
                    await process_batch(list_of_titles, list_of_companies, list_of_links)
                    list_of_titles.clear()
                    list_of_companies.clear()
                    list_of_links.clear()
                    await helper.update_processed_jobs(list_of_processed_jobs)
                    list_of_processed_jobs.clear()

            # Pagination
            try:
                button_locator = page.locator(f"[aria-label='Page {pagination_number + 1}']")
                await button_locator.wait_for(timeout=10000)
                await button_locator.click()
                logging.info(f"Successfully click: {pagination_number + 1}")
                pagination_number += 1
            except Exception:
                filename = f"screenshot_{pagination_number}.png"
                file_path = os.path.join(config_input.DEBUGGING_SCREENSHOTS_PATH, filename)
                await page.screenshot(path=file_path, full_page=True)
                logger.info(f"No more pages. Screenshot saved: {file_path} \n {link}")
                break

        # Final batch processing if any remain
        if list_of_titles:
            await process_batch(list_of_titles, list_of_companies, list_of_links)
            await helper.update_processed_jobs(list_of_processed_jobs)

    except Exception:
        logger.exception("Error in _listing")
    finally:
        try:
            if page:
                await page.close()
            # ⚠️ don’t always close context here if it's reused 
            await context.close()
            logger.debug("Page closed")
        except Exception as e:
            logger.error(f"Cleanup issue: {e}")

async def process_batch(list_of_titles, list_of_companies, list_of_links):
    prompt = f"""{config_input.AI_PROMPT}\n
{config_input.RESUME}\n
Jobs Titles:
{list_of_titles}
    """
    try:
        # model_response = await helper.get_match_percentage_from_gemini(prompt)
        model_response = await helper.get_match_percentage_from_groq(prompt)
        logger.info(f"Model response: {model_response}")

        matching_percentages = re.findall(r'\b\d+\b', model_response)
        matching_percentages = list(map(int, matching_percentages))

        # Recreate empty list and save with matching numbers
        rows = []
        for company, title, link, percentage in zip(list_of_companies, list_of_titles, list_of_links, matching_percentages):
            if percentage >= config_input.MATCHING_PERCENTAGE:
                # Build a row
                row = [company, title, link, percentage]
                rows.append(row)
      
       # Now let save scraped jobs
        if rows:
            await helper.update_csv_with_new_jobs(config_input.CSV_FILE, rows)
    except Exception:
        logger.exception("Batch processing failed")

async def jobs_lister(chunk_urls):
    try:
        proxies = await proxies_loader.load_proxies()
        accounts = await accounts_loader.load_accounts()
    except Exception:
        logger.exception("Error loading context data")

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=config_input.headless,
            #  args=[
            #     "--disable-background-timer-throttling",
            #     "--disable-renderer-backgrounding",
            #     "--disable-backgrounding-occluded-windows"
            # ]
            )
        tasks = []

        for index, job_page_url in enumerate(chunk_urls):
            try:
                context = await browser.new_context(
                    proxy=proxies[index],
                    # viewport={"width": 1280, "height": 800},
                    is_mobile=True,
                    has_touch=True
                )

                script = await fingerprint_loader.load_fingerprint(index)
                await context.add_init_script(script=script)

                if index == 0:
                    logger.info(f"Total {len(chunk_urls)} contexts launched.")

                try:
                    await context.add_cookies(accounts[index])
                except:
                    await context.add_cookies(random.choice(accounts))

                tasks.append(_listing(context, job_page_url))
            except Exception:
                logger.exception("Context creation failed")

        await asyncio.gather(*tasks)








