#!/usr/bin/python3
import asyncio
import io
import os
import shutil
import ssl
import zipfile

import aiohttp
import git
import github


def generate_readme(variant, release):
    readme = """# {variant_cap} WebFont {release}

## How to use

- Add `<link href="https://iosevka-webfonts.github.io/{variant}/{variant_css}.css" rel="stylesheet" />` to your `<head>`.
- Use `fontFamily: '{samplefont}'` or `font-family: '{samplefont}'`.
"""

    variant_cap = " ".join(e.capitalize() if not e.startswith(
        "ss") else e.upper() for e in variant.split("-"))
    variant_css = variant
    if "unhinted" in variant:
        variant_css = f"{variant.removeprefix('unhinted-')}-unhinted"
    samplefont = f"{variant_cap} Web".replace("Unhinted ", "")
    return readme.format(variant_cap=variant_cap, variant=variant,
                         variant_css=variant_css, release=release,
                         samplefont=samplefont)


def clone_repo(org_name: str, repo_name: str):
    print(f"  - Cloning repo {repo_name}")
    g = github.Github(login_or_token=os.getenv("GITHUB_TOKEN"),
                      verify=False)
    # Check repo
    repo = None
    try:
        repo = g.get_repo(f"{org_name}/{repo_name}")
    except github.UnknownObjectException:
        org = g.get_organization(org_name)
        repo = org.create_repo(repo_name, license_template="apache-2.0",
                               auto_init=True)
        # Configure Github pages
        # NOTE(kiennt26): PyGithub doesn't support configure
        #                 a Github Page site.
        requester = github.Requester.Requester(
            os.getenv("GITHUB_TOKEN"),
            password=None,
            jwt=None,
            base_url=github.MainClass.DEFAULT_BASE_URL,
            timeout=github.MainClass.DEFAULT_TIMEOUT,
            user_agent="PyGithub/Python",
            per_page=github.MainClass.DEFAULT_PER_PAGE,
            verify=False,
            retry=None,
            pool_size=None,
        )
        requester.requestJsonAndCheck(
            "POST",
            f"{repo.url}/pages",
            input={"source": {"branch": "main", "path": "/"}}  # hardcode
        )

    # Clone
    remote_url = f"https://{os.getenv('GITHUB_USERNAME')}:"\
        f"{os.getenv('GITHUB_TOKEN')}@github.com/{org_name}/{repo_name}.git"
    return git.Repo.clone_from(remote_url, repo_name)


def commit_all_repo(repo: git.Repo, commit_msg: str):
    # If there is nothing changed, ignore it
    # to handle empty 'git commit'
    if not repo.git.status(short=True):
        return
    print(f"  - Commit all files in repo {repo.working_tree_dir}")
    # Use git directly
    repo.git.add(".")
    repo.git.commit(m=commit_msg)
    repo.git.push()


def check_release(latest_release, release_path):
    # Force update
    force_update = os.getenv("FORCE_UPDATE", "false")
    if force_update.lower() == "true":
        # simply remove release file
        os.remove(release_path)

    if os.path.exists(release_path):
        with open(release_path) as f:
            current_release = f.read()
            if current_release == latest_release:
                print(f"  - Release {current_release} is up-date-to, skip...")
                return True

    # Update the latest release
    with open(release_path, "w") as f:
        f.write(latest_release)
    return False


async def fetch_asset(session: aiohttp.ClientSession, release: str,
                      asset_name: str, asset_download_url: str):
    # Preprocess variant name, for example:
    # webfont-iosevka-17.1.0.zip -> iosevka
    variant = asset_name.removeprefix("webfont-").\
        removesuffix(f"-{release}.zip")
    print(f"* Updating repo {variant}:")
    # Hardcode here!
    repo = clone_repo(org_name="iosevka-webfonts", repo_name=variant)

    # Check if the release already up-to-date
    if check_release(release, os.path.join(repo.working_tree_dir, "LATEST_RELEASE")):
        # Do clean to free disk space
        shutil.rmtree(variant)
        return

    print(f"  - Downloading asset {asset_name}")
    async with session.get(asset_download_url) as resp:
        zip_resp = await resp.read()
        z = zipfile.ZipFile(io.BytesIO(zip_resp))
        z.extractall(f"{variant}")
        print(f"  - Downloaded asset {asset_name} "
              f"and extracted to latest/{variant}")

        # Update README
        with open(os.path.join(repo.working_tree_dir, "README.md"), "w") as f:
            f.write(generate_readme(variant, release))

        commit_all_repo(repo,
                        commit_msg=f"Update {variant}-{release}")

    # Do clean to free disk space
    shutil.rmtree(variant)


async def fetch():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # NOTE(kiennt26): This is a workaround with SSL handshake issue
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.set_ciphers("DEFAULT")
    # trust_env -> Get proxy environment variables and use it
    # raise_for_status -> Raise an aiohttp.ClientResponseError
    # if the response status is 400 or higher.
    async with aiohttp.ClientSession(
            headers=headers,
            trust_env=True,
            connector=aiohttp.TCPConnector(ssl=ssl_ctx),
            raise_for_status=True) as session:
        # Get latest release
        latest_url = "http://api.github.com/repos/be5invis/Iosevka/releases/latest"
        async with session.get(latest_url) as resp:
            latest = await resp.json()
            print(f"Fetching Iosevka release {latest['tag_name']}...")

            for asset in latest["assets"]:
                # Filter webfont
                if "webfont" in asset["name"]:
                    release = latest["tag_name"].strip("v")  # number only
                    # Fetch all webfont asset
                    await fetch_asset(session, release, asset["name"],
                                      asset["browser_download_url"])

if __name__ == "__main__":
    print("##########################")
    print("# Get the latest release #")
    print("##########################")
    asyncio.run(fetch())
    print("########")
    print("# Done #")
    print("########")
