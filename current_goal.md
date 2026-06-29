目前需要复现 /mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B 在 OSWorld-Verified的结果

其他信息:东西下载可以从ssh nas下载;我已经在nas上下好了/data/ruanjunhao/zhaorunsong/repo/xlangai/ubuntu_osworld

目前已经完成了一次复现，并把文档归档在/mnt/zhaorunsong/repo/CUA/复现_LLM.md和/mnt/zhaorunsong/repo/CUA/复现.md

我将写代码的模型切换至sonnet，结果sonnet利用复现文档只跑出了四十多，而官网上的结果有七十多。
sonnet固执地认为4B模型就应该只有四十多分，有可能是训练数据产生的幻觉，因为过去的模型确实没那么强。这个七十多分的/mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B是刚出的模型不在sonnet的先验知识里也确实可能。
同时sonnet还有一个风险行为，就是直接把网络崩溃或无权限的任务直接给0分，而不去解决环境问题。


现在我需要把模型切换至opus，先让opus做好复现debug的规划，再让sonnet执行。

目前，我手动从/mnt/zhaorunsong/repo/CUA/Env/OSWorld/results/pyautogui/screenshot/Holo-3.1-4B/multi_apps/0c825995-5b70-4526-b663-113f4c999dd2/report.html等文件找到了一些**并非模型能力**导致的失败结果

比如：
1. 因网络问题出错
2. 权限问题出错
3. 谷歌网盘
这些属于环境和权限问题，可以让sonnet自己解决，或者向我寻求帮助。


同时我担心一些代码严谨性问题。我担心sonnet私自改动了代码，使结果不可信。
最后，OSWorld有一些任务应该是无法完成的，目前这个信息没有记录在results里，因为我无法确认正确答案是什么。即我无法确认，我是要去解决环境问题，还是实际上只要模型输出不可行就行。


请opus做好复现debug的规划，再让sonnet执行。



