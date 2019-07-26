'''
此代码爬取湖南的开庭公告，
'''

import requests
import time
from requests.exceptions import Timeout,ConnectionError
from lxml import etree
import pymysql
import re
import redis
import hashlib

class Ktgg_hunan(object):
    def __init__(self):
        # 链接mysql数据库
        self.db = pymysql.connect(host="localhost",user="root",password="123456",db='litianming')
        self.cursor = self.db.cursor()

        # 定义正则表达式
        self.re = [
            '于(.*?)\\s.*?本院(.*?)公开审理(.*?)诉(.*?)%s',
            '于(.*?)\\s.*?本院(.*?)公开审理(.*?)%s',
            '于(.*?)在(.*?)公开审理(.*?)诉(.*?)%s',
            '于(.*?)在(.*?)公开审理(.*?)%s',
            '于(.*?)在(.*?)审理(.*?)诉(.*?)%s',
            '于(.*?)在(.*?)审理(.*?)%s',
            ]

        # 定义案由
        self.anyou = ''

        # 定义去除详情页非数据标识
        self.biaoshi = ['法院公告','开庭公告']

        # 定义请求头headers
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Host": "hnjhfy.chinacourt.gov.cn",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
            }

        # 起始url 
        self.url = "http://hnjhfy.chinacourt.gov.cn/article/index/id/M0gzNjCwNDAwNCACAAA/page/1.shtml"

    # 获取所有的案由
    def set_anyou(self):
        r = redis.Redis(host='127.0.0.1',port=6379,db=0)
        self.anyou = r.lrange('anyou', 0, -1)

    # 构建一级链接请求并且请求获得响应
    def set_request(self):
        print('正在获取详情页链接....')
        # 更改起始页
        i = 1
        link_list = []
        while True:
            new = str(i) + '.shtml'
            old = self.url.split('/')[-1]
            url = self.url.replace(old,new)
            try:
                re = requests.get(url,headers=self.headers,timeout=3.05)
                re.encoding = 'utf8'
                html = re.text
            except (Timeout,ConnectionError):
                continue
            text = etree.HTML(html)
            urls = text.xpath('//div[@class="paginationControl"]/following-sibling::ul//a/@href')
            names = text.xpath('//div[@class="paginationControl"]/following-sibling::ul//a/text()')
            for x,y in zip(names,urls):
                for s in self.biaoshi:
                    if s in x:
                        link_list.append(y)
                        break
            if not urls:
                break
            i += 1
        print('详情链接请求到的个数有: ' + str(len(link_list)))
        return link_list

    # 进行详情页的请求并且解析
    def request_info(self,links):
        for i in links:
            d = {}
            url = 'http://hnjhfy.chinacourt.gov.cn' + i
            while True:
                try:
                    re = requests.get(url,headers=self.headers,timeout=3.05)
                    re.encoding = 'utf8'
                    html = re.text
                except (Timeout,ConnectionError):
                    continue
                break
            
            # 获取所有的文本内容
            text = etree.HTML(html)
            content = text.xpath('//div[@class="text"]')
            if content == []:
                continue
            info = content[0].xpath('string(.)')
            # with open('info.txt','a',encoding='utf-8') as f:
            #     f.write(info)
            #     f.write('\n')
            #     f.write('----------------')
            #     f.write('\n')

            # 先获取一些字段
            d['source'] = self.url
            d['url'] = url
            d['title'] = text.xpath('//div[@class="b_title"]/text()')[0]
            d['court'] = '湖南省嘉禾县人民法院'
            d['posttime'] = text.xpath('//div[@class="sth_a"]/span[1]/text()')[0].strip().split('：')[-1]
            d['province'] = '湖南省'
            self.parse(info,d)

    # 解析文本提取字段
    def parse(self,info,d):
        # 由于文本原因需要分两种情况解析页面
        if '2010' not in d['title']:
            text = re.findall('(.*?)一案。',info)
            for t in text:
                d['body'] = t.replace('\u3000','').strip()

                # 获取案由
                l = []
                for anyou in self.anyou:
                    if anyou.decode('utf-8') in t:
                        l.append(anyou.decode('utf-8'))
                l.sort(reverse=True,key=len)
                try:
                    d['anyou'] = l[0]
                except IndexError:
                    continue

                for i in self.re:
                    # 提取想要的信息
                    try:
                        l = re.findall(i % d['anyou'],t)[0]
                        if len(l) == 3:
                            d['plaintiff'] = ''
                            d['pname'] = l[2].strip()
                        else:
                            d['plaintiff'] = l[2].strip()
                            d['pname'] = l[3].strip()
                        d['sorttime'] = l[0].strip()
                        d['courtNum'] = l[1].strip()
                        break
                    except IndexError:
                        continue

                # 生成MD5
                md5 = hashlib.md5()
                md5.update((d['body'] + d['url']).encode())
                d['md5'] = md5.hexdigest()
                self.insert_mysql(d)
        else:
            text = info.split('湖南省嘉禾县人民法院')
            for t in text[1:]:
                # 对文本做处理
                t = t.replace('\r\n','').replace('\xa0','').replace(' ','')
                d['body'] = t
                # 提取案由
                l = []
                for anyou in self.anyou:
                    if anyou.decode('utf-8') in t:
                        l.append(anyou.decode('utf-8'))
                l.sort(reverse=True,key=len)
                try:
                    d['anyou'] = l[0]
                except IndexError:
                    continue
                try:
                    # 提取被告
                    d['pname'] = re.findall('公告(.*?)：',t)[0]
                    # 提取原告
                    d['plaintiff'] = re.findall('原告(.*?)[诉与]',t)[0]
                except IndexError:
                    continue
                # 提取开庭时间
                try:
                    d['sorttime'] = re.findall('并定于(.*?日)',t)[0]
                except IndexError:
                    d['sorttime'] = ''
                # 提取庭审地点
                try:
                    d['courtNum'] = re.findall('在(.*?)公开',t)[0]
                except IndexError:
                    d['courtNum'] = ''
                # 提取庭审号
                try:
                    d['caseNo'] = re.findall('送达(.*?号)',t)[0]
                except IndexError:
                    d['caseNo'] = ''
                md5 = hashlib.md5()
                md5.update((d['body'] + d['url']).encode())
                d['md5'] = md5.hexdigest()
                self.insert_mysql(d)

    # 对数据的入库和清洗
    def insert_mysql(self,d):
        # 删除没有值的字段
        l = []
        for i in d.keys():
            if d[i] == '':
                l.append(i)
        for i in l:
            del d[i]

        # 准备入库
        table = 'ktgg_hunan1'
        keys = ','.join(d.keys())
        values = ','.join(['%s'] * len(d))
        sql = "INSERT INTO {table}({keys}) VALUES({values})".format(table = table,keys = keys,values = values)
        try:
            self.cursor.execute(sql,tuple(d.values()))
            self.db.commit()
        except:
            self.db.rollback()
    
    # 关闭数据库连接
    def close_mysql(self):
        self.cursor.close()
        self.db.close()

    # 函数的控制
    def main(self):
        self.set_anyou()
        links = self.set_request()
        self.request_info(links)
        self.close_mysql()

if __name__ == "__main__":
    kh = Ktgg_hunan()
    kh.main()


