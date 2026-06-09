import json
import logging
import os
import time

import requests
from colorama import Fore, Style, init

import config
import login
from course import CourseManager

init()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

session = requests.Session()


def get_headers(token):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36",
        "token": token,
        "authToken": token,
        "siteId": "95",
        "Content-Type": "application/json",
    }


def _load_credentials_store():
    if not os.path.exists(config.CREDENTIALS_FILE):
        return {}
    try:
        with open(config.CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"{Fore.RED}加载凭证失败: {e}{Style.RESET_ALL}")
        return {}

    if not isinstance(data, dict):
        return {}

    if "loginName" in data and "token" in data:
        login_name = data["loginName"]
        return {login_name: data}

    return data


def _save_credentials_store(store):
    with open(config.CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def save_credentials(loginName, passWord, token):
    store = _load_credentials_store()
    store[loginName] = {
        "loginName": loginName,
        "passWord": passWord,
        "token": token,
        "timestamp": int(time.time()),
    }
    _save_credentials_store(store)
    logging.info(f"{Fore.GREEN}凭证已保存: {loginName}{Style.RESET_ALL}")


def get_saved_account(loginName):
    return _load_credentials_store().get(loginName)


def get_all_saved_accounts():
    store = _load_credentials_store()
    return list(store.values())


def login_with_saved_or_password(loginName, passWord):
    saved = get_saved_account(loginName)
    if saved and saved.get("token") and check_login(saved["token"]):
        print(f"{Fore.GREEN}使用已保存的 token 登录成功: {loginName}{Style.RESET_ALL}")
        pwd = passWord or saved.get("passWord", "")
        if pwd and saved.get("passWord") != pwd:
            save_credentials(loginName, pwd, saved["token"])
        return loginName, pwd or saved.get("passWord", ""), saved["token"]

    return perform_login(loginName, passWord)


def select_saved_account():
    saved_accounts = get_all_saved_accounts()
    if not saved_accounts:
        return None

    account_rows = []
    for account in saved_accounts:
        login_name = account.get("loginName", "")
        token = account.get("token")
        if not login_name or not token:
            continue
        nickname = check_login(token)
        account_rows.append(
            {
                "loginName": login_name,
                "passWord": account.get("passWord", ""),
                "token": token,
                "valid": bool(nickname),
                "nickname": nickname if nickname else "已过期",
            }
        )

    if not account_rows:
        return None

    valid_rows = [row for row in account_rows if row["valid"]]
    if not valid_rows:
        print(f"{Fore.YELLOW}发现 {len(account_rows)} 个已保存账号，但 token 均已过期{Style.RESET_ALL}")
        return None

    if len(valid_rows) == 1:
        row = valid_rows[0]
        display_name = row["nickname"] if row["nickname"] != "未设定姓名" else row["loginName"]
        print(f"{Fore.YELLOW}发现保存的账号: {row['loginName']} ({display_name}){Style.RESET_ALL}")
        choice = input(
            f"{Fore.CYAN}是否使用保存的凭证自动登录? (直接回车使用，输入 n 跳过): {Style.RESET_ALL}"
        ).strip().lower()
        if choice == "n":
            return None
        return row["loginName"], row["passWord"], row["token"]

    print(f"{Fore.YELLOW}发现 {len(valid_rows)} 个已保存且有效的账号:{Style.RESET_ALL}")
    for index, row in enumerate(valid_rows, start=1):
        display_name = row["nickname"] if row["nickname"] != "未设定姓名" else row["loginName"]
        print(f"  {index}. {row['loginName']} ({display_name})")

    choice = input(
        f"{Fore.CYAN}请选择账号编号 (直接回车或输入 n 跳过): {Style.RESET_ALL}"
    ).strip().lower()
    if choice in ("", "n"):
        return None

    try:
        index = int(choice) - 1
        if 0 <= index < len(valid_rows):
            row = valid_rows[index]
            return row["loginName"], row["passWord"], row["token"]
    except ValueError:
        pass

    print(f"{Fore.RED}无效的账号编号{Style.RESET_ALL}")
    return None


def check_login(token):
    if not token:
        return False

    headers = get_headers(token)
    url = "https://www.baomi.org.cn/portal/main-api/checkToken.do"
    try:
        response = session.get(url, headers=headers).json()
        if response.get("result"):
            nickname = response["data"].get("nickName")
            return nickname or "未设定姓名"
    except Exception as e:
        logging.error(f"{Fore.RED}检查 token 失败: {e}{Style.RESET_ALL}")
    return False


def _is_valid_account(loginName, passWord):
    return bool(loginName and passWord and loginName != "xxxx" and passWord != "xxxx")


def get_config_accounts():
    accounts = []

    config_accounts = getattr(config, "accounts", None)
    if config_accounts:
        for item in config_accounts:
            if isinstance(item, dict):
                loginName = item.get("loginName", "")
                passWord = item.get("passWord", "")
                label = item.get("label", "")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                loginName, passWord = item[0], item[1]
                label = item[2] if len(item) > 2 else ""
            else:
                continue
            if _is_valid_account(loginName, passWord):
                accounts.append({"loginName": loginName, "passWord": passWord, "label": label})

    login_name = getattr(config, "loginName", "")
    pass_word = getattr(config, "passWord", "")
    if not accounts and _is_valid_account(login_name, pass_word):
        accounts.append(
            {"loginName": login_name, "passWord": pass_word, "label": ""}
        )

    return accounts


def select_config_account():
    accounts = get_config_accounts()
    if not accounts:
        return None

    if len(accounts) == 1:
        account = accounts[0]
        display_name = account["label"] or account["loginName"]
        print(f"{Fore.YELLOW}检测到 config.py 中已配置账号: {display_name}{Style.RESET_ALL}")
        choice = input(
            f"{Fore.CYAN}是否使用该账号登录? (直接回车使用，输入 n 跳过): {Style.RESET_ALL}"
        ).strip().lower()
        if choice == "n":
            return None
        return account["loginName"], account["passWord"]

    print(f"{Fore.YELLOW}检测到 config.py 中已配置 {len(accounts)} 个账号:{Style.RESET_ALL}")
    for index, account in enumerate(accounts, start=1):
        display_name = account["label"] or account["loginName"]
        print(f"  {index}. {display_name} ({account['loginName']})")

    choice = input(
        f"{Fore.CYAN}请选择账号编号 (直接回车或输入 n 跳过): {Style.RESET_ALL}"
    ).strip().lower()
    if choice in ("", "n"):
        return None

    try:
        index = int(choice) - 1
        if 0 <= index < len(accounts):
            account = accounts[index]
            return account["loginName"], account["passWord"]
    except ValueError:
        pass

    print(f"{Fore.RED}无效的账号编号{Style.RESET_ALL}")
    return None


def perform_login(loginName, passWord):
    token = login.login(loginName, passWord)
    print(f"{Fore.GREEN}登录成功，已获取 token{Style.RESET_ALL}")
    save_credentials(loginName, passWord, token)
    print(f"{Fore.GREEN}已自动保存凭证{Style.RESET_ALL}")
    return loginName, passWord, token


def get_user_credentials():
    saved_creds = select_saved_account()
    if saved_creds:
        loginName, passWord, token = saved_creds
        print(f"{Fore.GREEN}使用已保存的凭证登录成功{Style.RESET_ALL}")
        return loginName, passWord, token

    config_creds = select_config_account()
    if config_creds:
        loginName, passWord = config_creds
        try:
            return login_with_saved_or_password(loginName, passWord)
        except Exception as e:
            print(f"{Fore.RED}登录失败: {e}{Style.RESET_ALL}")

    print(f"{Fore.CYAN}请输入新凭证进行登录{Style.RESET_ALL}")
    loginName = input(f"{Fore.CYAN}请输入用户名: {Style.RESET_ALL}")
    passWord = input(f"{Fore.CYAN}请输入密码: {Style.RESET_ALL}")
    try:
        return perform_login(loginName, passWord)
    except Exception as e:
        print(f"{Fore.RED}登录失败: {e}{Style.RESET_ALL}")
        return get_user_credentials()


def display_course_menu():
    print(f"\n{Fore.CYAN}============ 课程管理菜单 ============{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}1. 查看课程目录{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}2. 查看课程进度{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}3. 开始学习课程{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}4. 完成课程考试{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}0. 退出程序{Style.RESET_ALL}")
    return input(f"\n{Fore.CYAN}请选择操作 (0-4): {Style.RESET_ALL}")


def handle_course_menu(course_manager, course_packet_id):
    while True:
        choice = display_course_menu()

        if choice == "0":
            print(f"\n{Fore.GREEN}感谢使用，再见！{Style.RESET_ALL}")
            break
        if choice == "1":
            course_info = course_manager.get_course_info(course_packet_id)
            if course_info and course_info.get("data"):
                print(f"\n{Fore.GREEN}当前课程: {course_info['data']['name']}{Style.RESET_ALL}")
                print(f"课程说明: {course_info['data']['note']}")

                directory = course_manager.get_course_directory(course_packet_id)
                if directory and directory.get("data"):
                    print(f"\n{Fore.CYAN}课程目录:{Style.RESET_ALL}")
                    for section in directory["data"]:
                        print(f"\n{Fore.YELLOW}{section['name']}{Style.RESET_ALL}")
                        for sub in section["subDirectory"]:
                            print(f"  - {sub['name']}")
        elif choice == "2":
            progress = course_manager.get_course_progress(course_packet_id)
            if progress and progress.get("data"):
                data = progress["data"]
                print(f"\n{Fore.CYAN}课程进度信息:{Style.RESET_ALL}")
                print(f"课程名称: {data['courseName']}")
                print(f"学习进度: {data['progressRate'] * 100:.1f}%")
                print(f"已学课程数: {data['studyResourceNum']}/{data['resourceSum']}")
                print(f"总学习时长: {data['totalStudyTime']} 秒")
                print(f"是否完成: {'是' if data['isFinish'] else '否'}")
                print(f"是否获得证书: {'是' if data['isCertificate'] else '否'}")
        elif choice == "3":
            print(f"\n{Fore.CYAN}开始自动学习课程...{Style.RESET_ALL}")
            if course_manager.study_course(course_packet_id):
                print(f"\n{Fore.GREEN}课程学习完成！{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.RED}课程学习失败，请稍后重试{Style.RESET_ALL}")
        elif choice == "4":
            print(f"\n{Fore.CYAN}开始自动完成考试...{Style.RESET_ALL}")
            if course_manager.complete_exam(course_packet_id):
                print(f"\n{Fore.GREEN}考试完成！{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.RED}考试完成失败，请稍后重试{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.RED}无效的选择，请重试{Style.RESET_ALL}")


if __name__ == "__main__":
    print(f"{Fore.CYAN}============ 保密教育登录程序 ============{Style.RESET_ALL}")
    loginName, passWord, token = get_user_credentials()

    nickname = check_login(token)
    if nickname:
        print(f"{Fore.GREEN}登录成功! 欢迎, {nickname}{Style.RESET_ALL}")
        course_manager = CourseManager(session, token)
        handle_course_menu(course_manager, config.course_packet_id)
    else:
        print(f"{Fore.RED}登录失败或 token 无效{Style.RESET_ALL}")
