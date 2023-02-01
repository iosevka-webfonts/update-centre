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
    print(f"  - Commit all files in repo {repo.working_tree_dir}")
    # Use git directly
    repo.git.add(".")
    repo.git.commit(m=commit_msg)
    repo.git.push()


async def fetch_asset(session: aiohttp.ClientSession, release: str,
                      asset_name: str, asset_download_url: str):
    # Preprocess variant name, for example:
    # webfont-iosevka-17.1.0.zip -> iosevka
    variant = asset_name.removeprefix("webfont-").\
        removesuffix(f"-{release}.zip")
    print(f"* Updating repo {variant}:")
    # Hardcode here!
    repo = clone_repo(org_name="iosevka-webfonts", repo_name=variant)
    print(f"  - Downloading asset {asset_name}")
    async with session.get(asset_download_url) as resp:
        zip_resp = await resp.read()
        z = zipfile.ZipFile(io.BytesIO(zip_resp))
        z.extractall(f"{variant}")
        print(f"  - Downloaded asset {asset_name} "
              f"and extracted to latest/{variant}")
        # Update README
        with open(os.path.join(repo.working_tree_dir, "README.md"), "w") as f:
            f.write(f"{variant.capitalize} - version {release}")

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
            # Check if the release already exists
            if os.path.exists("LATEST_RELEASE"):
                with open("LATEST_RELEASE") as f:
                    current_version = f.read()
                    if current_version == latest["tag_name"]:
                        print(f"Release {current_version} already exists,"
                              "up-to-date, skip!")
                        return

            print(f"Fetching Iosevka release {latest['tag_name']}...")

            for asset in latest["assets"]:
                # Filter webfont
                if "webfont" in asset["name"]:
                    release = latest["tag_name"].strip("v")  # number only
                    # Fetch all webfont asset
                    await fetch_asset(session, release, asset["name"],
                                      asset["browser_download_url"])

        # Update the latest release
        with open("LATEST_RELEASE", "w") as f:
            f.write(latest["tag_name"])

if __name__ == "__main__":
    print("##########################")
    print("# Get the latest release #")
    print("##########################")
    asyncio.run(fetch())
    print("########")
    print("# Done #")
    print("########")
