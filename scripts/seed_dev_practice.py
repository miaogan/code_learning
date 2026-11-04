"""生成「研发工程实践」方向题库的 **staging 素材文件**（canonical 输入）。

本脚本只产出 `docs/question-bank-staging/09-dev-practice.json`；`question_merge`
从该文件 + 存量重建 `app/seed/questions.json`（写完 staging 后跑
`python -m app.services.question_merge --write`）。

约束（与产品闭集一致）：
- 方向 direction = "研发工程实践"（rules.DIRECTIONS 已新增，第 8 个一等方向）
- 语言 language = ""（通用题，不带语言方向）
- 来源 source = "devprac"（question_merge.SOURCES 已新增；由 STAGING 文件名决定）
- kind ∈ {single, multiple, judge}（合并批不允许 text）

选项长度纪律：正确项平均长度 ≤ 干扰项平均的 2.9 倍（`question_shuffle` 的
`_LENGTH_RATIO_LONG` 门禁是 3 倍，这里留 0.1 余量），validate() 会硬校验。

判断题极性纪律：本批 11 道判断题里只有 1 道答「正确」、10 道答「错误」。
通用语言桶原有 105 道判断题（61 正确 / 44 错误，占比 0.581），加入后
(61+1)/(105+11) = 0.534，仍落在 `JUDGE_TRUE_RATIO` 的 0.4–0.6 内。
新增判断题不要写进 `question_shuffle.JUDGE_FLIPS`（那是存量行的极性改写表）。

幂等：重跑会整体重写该 staging 文件。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_PATH = ROOT / "docs" / "question-bank-staging" / "09-dev-practice.json"

JUDGE_OPTIONS = [
    {"key": "A", "text": "正确"},
    {"key": "B", "text": "错误"},
]


def q(
    qid: str,
    kind: str,
    difficulty: str,
    essentiality: str,
    prompt: str,
    options: list[dict],
    answer: list[str],
    explanation: str,
) -> dict:
    return {
        "id": qid,
        "kind": kind,
        "difficulty": difficulty,
        "essentiality": essentiality,
        "language": "",
        "direction": "研发工程实践",
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
    }


def opt(*pairs: tuple[str, str]) -> list[dict]:
    return [{"key": k, "text": t} for k, t in pairs]


QUESTIONS: list[dict] = []

# ---- Git 与版本控制（12）----
QUESTIONS += [
    q("dev-git-1", "single", "basic", "must_know",
      "在 Git 中，`git add` 的作用是什么？",
      opt(("A", "把工作区改动写入暂存区，供下次提交使用"),
          ("B", "把改动直接推送到远程仓库并合并"),
          ("C", "把当前分支切换到指定的提交记录"),
          ("D", "把本地仓库压缩打包成一个归档文件")),
      ["A"],
      "add 把改动放进暂存区（index），commit 只提交暂存区内容；未 add 的改动不会被提交。"),
    q("dev-git-2", "single", "intermediate", "advanced",
      "`git commit -am 'msg'` 不能处理哪类改动？",
      opt(("A", "尚未被 Git 跟踪的新文件，仍需先 git add"),
          ("B", "已被跟踪文件的内容修改，照常可以提交"),
          ("C", "已被跟踪文件的删除操作，照常可以提交"),
          ("D", "已被跟踪文件的重命名，照常可以提交")),
      ["A"],
      "-a 只对「已跟踪」文件的修改与删除生效；未跟踪文件必须先 git add 才能进提交。"),
    q("dev-git-3", "single", "basic", "must_know",
      "`git pull` 相对于 `git fetch` 多了哪一步？",
      opt(("A", "取回远程更新后再合并（或变基）到当前分支"),
          ("B", "取回更新后自动推送本地提交到服务端"),
          ("C", "取回更新后自动删除本地所有未提交改动"),
          ("D", "取回更新后自动为每次提交打一个版本标签")),
      ["A"],
      "fetch 只更新远程跟踪分支、不动工作区；pull = fetch + merge（或配置成 rebase）。"),
    q("dev-git-4", "single", "intermediate", "must_know",
      "关于 `git rebase` 与 `git merge`，下列说法正确的是？",
      opt(("A", "rebase 把提交重放到目标分支之上，历史更线性"),
          ("B", "merge 会把当前分支的提交逐个改写后重放"),
          ("C", "rebase 一定会生成一个额外的合并提交"),
          ("D", "merge 会改写已有提交的作者与提交时间")),
      ["A"],
      "rebase 重放提交形成线性历史、但改写了 commit id；merge 保留原提交并新增合并节点。已推送的公共分支不要随意 rebase。"),
    q("dev-git-5", "judge", "intermediate", "advanced",
      "`git reset --hard` 会丢弃工作区中尚未提交的改动。",
      JUDGE_OPTIONS, ["A"],
      "--hard 会把 HEAD、暂存区和工作区一起重置到目标提交，未提交的改动无法找回，使用前务必确认。"),
    q("dev-git-6", "judge", "intermediate", "advanced",
      "`git revert` 通过改写已有提交历史来撤销某次改动。",
      JUDGE_OPTIONS, ["B"],
      "revert 新建一个「反向提交」来抵消改动，不改写历史，因此对已推送的公共分支更安全。"),
    q("dev-git-7", "single", "basic", "must_know",
      "开发到一半需要临时切换分支处理线上问题，最合适的做法是？",
      opt(("A", "用 git stash 暂存当前改动，回来后再恢复"),
          ("B", "把半成品直接 commit 并推送到主干分支"),
          ("C", "用 git reset --hard 清空改动，之后再重写"),
          ("D", "把整个仓库复制一份，改完再手工合并回来")),
      ["A"],
      "stash 把未提交的改动存起来并还原工作区，切分支处理完再用 stash pop 恢复。"),
    q("dev-git-8", "single", "intermediate", "advanced",
      "`git cherry-pick` 的典型用途是？",
      opt(("A", "把某个提交的改动单独应用到当前分支"),
          ("B", "把两个分支的历史完全合并成一条线"),
          ("C", "永久删除远程仓库里的某次提交记录"),
          ("D", "统计每个文件的提交次数与作者分布")),
      ["A"],
      "常用于把修复提交从主干单独搬到发布分支；它会生成内容相同但 commit id 不同的新提交。"),
    q("dev-git-9", "multiple", "challenge", "nice_to_know",
      "下列哪些场景适合使用 `git rebase`？",
      opt(("A", "整理本地尚未推送的多个零散提交"),
          ("B", "把主干最新提交作为基底，保持特性分支线性"),
          ("C", "重写团队共享主干上已被他人基于开发的历史"),
          ("D", "修复已经推送到公共分支的提交哈希")),
      ["A", "B"],
      "rebase 适合清理本地未推送历史或同步主干；一旦提交已共享，重写会让他人分支产生冲突与分叉。"),
    q("dev-git-10", "single", "intermediate", "advanced",
      "往 `.gitignore` 加入某个已被 Git 跟踪的日志文件后，通常会？",
      opt(("A", "仍然继续跟踪它，需先 git rm --cached 才生效"),
          ("B", "立即从版本库删除该文件且本地副本也消失"),
          ("C", "自动把该文件历史上所有提交一并清除"),
          ("D", "让该文件从此不再出现在任何分支的目录里")),
      ["A"],
      ".gitignore 只对未跟踪文件生效；已跟踪文件要先 git rm --cached 停止跟踪，必要时再清理历史中的敏感内容。"),
    q("dev-git-11", "single", "challenge", "nice_to_know",
      "要定位「哪次提交引入了某个回归缺陷」，最合适的 Git 命令是？",
      opt(("A", "git bisect 在好/坏提交之间二分查找"),
          ("B", "git blame 自动回滚到上一个稳定版本"),
          ("C", "git reflog 逐行对比两个文件的差异"),
          ("D", "git tag 为每个提交批量生成版本号")),
      ["A"],
      "bisect 用二分法逐步标记 good/bad，能在大量提交里快速收敛到首个坏提交；配合自动化测试可全自动。"),
    q("dev-git-12", "judge", "challenge", "nice_to_know",
      "无法快进时，`git merge --ff-only` 会自动创建一个合并提交完成合并。",
      JUDGE_OPTIONS, ["B"],
      "--ff-only 要求必须能快进，否则直接报错退出、不产生任何合并提交；这样可保证历史不被意外分叉。"),
]

# ---- CI/CD 与流水线（10）----
QUESTIONS += [
    q("dev-cicd-1", "single", "basic", "must_know",
      "持续集成（CI）最核心的目标是什么？",
      opt(("A", "频繁合入并自动编译验证，尽早发现集成问题"),
          ("B", "把每次提交自动发布给全部线上用户"),
          ("C", "替代人工代码评审，完全取消人工确认"),
          ("D", "把生产环境的配置同步回开发机使用")),
      ["A"],
      "CI 强调小步频繁集成 + 自动化构建与测试，让冲突和缺陷在合入后几分钟内暴露。"),
    q("dev-cicd-2", "single", "intermediate", "must_know",
      "「持续交付」与「持续部署」的关键区别是？",
      opt(("A", "交付只保证随时可发布，部署则自动发布到生产"),
          ("B", "交付只跑单元测试，部署则只跑集成测试"),
          ("C", "交付面向前端项目，部署只面向后端服务"),
          ("D", "交付必须人工打包，部署必须人工审批")),
      ["A"],
      "持续交付让主干始终处于可发布状态、上线由人决定；持续部署则把通过门禁的变更自动送到生产。"),
    q("dev-cicd-3", "single", "basic", "must_know",
      "流水线中「质量门禁」的主要作用是？",
      opt(("A", "不达标就阻断后续阶段，防止缺陷流入下游"),
          ("B", "统计团队每日提交数量并排行展示"),
          ("C", "自动为每次构建生成一份发布说明文档"),
          ("D", "把构建日志压缩归档以节省磁盘空间")),
      ["A"],
      "门禁把 lint、类型检查、单测覆盖率、安全扫描等结果变成硬性条件，失败即停止发布。"),
    q("dev-cicd-4", "judge", "basic", "must_know",
      "只要 CI 构建通过，就可以跳过测试环节直接把变更发布到生产环境。",
      JUDGE_OPTIONS, ["B"],
      "构建通过只说明能编译打包；测试、评审与发布门禁各有职责，跳过会绕过质量防线。"),
    q("dev-cicd-5", "single", "intermediate", "advanced",
      "为什么构建产物要带唯一版本号且保持不可变？",
      opt(("A", "保证同一产物可追溯、可回滚、各环境一致"),
          ("B", "让每次构建的输出文件体积尽可能更小"),
          ("C", "使流水线无需记录任何构建元数据"),
          ("D", "避免产物需要在测试环境被安装依赖")),
      ["A"],
      "一次构建、多环境晋升（promote）才能避免「测过的和上线的不一样」；覆盖同名产物会破坏可追溯性。"),
    q("dev-cicd-6", "multiple", "basic", "must_know",
      "一条典型的 CI 流水线通常包含哪些阶段？",
      opt(("A", "静态检查与单元测试"),
          ("B", "编译构建与产物打包"),
          ("C", "镜像制作与部署到测试环境"),
          ("D", "直接删除生产数据库并重建")),
      ["A", "B", "C"],
      "流水线按「检查 → 构建 → 打包 → 部署验证」逐级推进；破坏性操作不属于常规流水线阶段。"),
    q("dev-cicd-7", "single", "intermediate", "advanced",
      "流水线里缓存依赖包，较稳妥的做法是？",
      opt(("A", "以锁文件内容的哈希作为缓存键，变更即失效"),
          ("B", "永久复用第一次构建的缓存，永不失效"),
          ("C", "按构建机器的主机名作为唯一缓存键"),
          ("D", "把依赖目录提交进代码仓库代替缓存")),
      ["A"],
      "锁文件 hash 能准确反映依赖变化；固定不过期的缓存会装进旧依赖，造成「本地正常、线上异常」。"),
    q("dev-cicd-8", "judge", "basic", "must_know",
      "为方便复用，应把访问令牌等密钥直接硬编码在流水线脚本里。",
      JUDGE_OPTIONS, ["B"],
      "密钥必须由密钥管理/变量注入提供并按最小权限授予；硬编码会随代码泄露且难以轮换。"),
    q("dev-cicd-9", "single", "intermediate", "advanced",
      "为什么 CI 要在干净的一次性环境中构建？",
      opt(("A", "排除开发机残留状态，让结果可复现、可审计"),
          ("B", "这样可以让构建速度恒定不受代码量影响"),
          ("C", "这样就不必在仓库里声明依赖版本"),
          ("D", "这样构建产物会自动获得生产环境权限")),
      ["A"],
      "干净环境能暴露「我本地是好的」这类隐式依赖；依赖必须显式声明并锁定版本。"),
    q("dev-cicd-10", "single", "challenge", "nice_to_know",
      "流水线偶发失败但重跑就通过，正确的处理方式是？",
      opt(("A", "定位并消除不确定性来源，如共享状态或时序依赖"),
          ("B", "配置自动无限重试直到某次通过为止"),
          ("C", "把失败用例从门禁中永久移除"),
          ("D", "把超时阈值调到足够大以掩盖波动")),
      ["A"],
      "偶发失败（flaky）会侵蚀对门禁的信任；应从测试隔离、资源竞争、外部依赖等根因入手，而非靠重试掩盖。"),
]

# ---- 需求对接与协作（10）----
QUESTIONS += [
    q("dev-req-1", "single", "basic", "must_know",
      "需求评审最核心的目的是什么？",
      opt(("A", "对齐理解、澄清边界并明确可验证的验收标准"),
          ("B", "当场确定每个接口的字段类型与命名"),
          ("C", "把开发排期压缩到尽可能短的天数"),
          ("D", "记录每位参会者的出勤与工时情况")),
      ["A"],
      "评审要解决「做什么、不做什么、怎样算做完」，把歧义在开工前暴露出来。"),
    q("dev-req-2", "single", "basic", "must_know",
      "一份合格的验收标准（AC）最应具备什么特征？",
      opt(("A", "描述可观察、可验证的条件，能判断通过与否"),
          ("B", "尽量使用「体验流畅」「性能良好」等形容词"),
          ("C", "只写正常路径，异常情况留给开发自行决定"),
          ("D", "只描述技术实现方案，不提用户可见结果")),
      ["A"],
      "可验证的 AC 是开发、测试、产品三方共同基准；含糊表述会让验收变成主观争论。"),
    q("dev-req-3", "judge", "basic", "must_know",
      "需求发生变更后，只要口头同步给开发，就不必更新需求文档与排期。",
      JUDGE_OPTIONS, ["B"],
      "变更需留痕并同步影响范围（文档、排期、测试与相关方），否则极易出现口径不一致与漏做。"),
    q("dev-req-4", "single", "intermediate", "advanced",
      "技术方案评审最应重点讨论的是什么？",
      opt(("A", "方案取舍、风险与对现有系统的影响面"),
          ("B", "代码缩进风格与变量命名是否统一"),
          ("C", "会议室排期与参会人员座位顺序"),
          ("D", "最终上线当天的值班餐食安排")),
      ["A"],
      "方案评审关注架构取舍、兼容性、回滚与成本；风格类问题交给 lint 与代码评审。"),
    q("dev-req-5", "single", "intermediate", "must_know",
      "把大需求拆成开发任务时，较合理的原则是？",
      opt(("A", "每个任务可独立实现、独立验证并明确依赖"),
          ("B", "按参与人数平均切分，不看功能边界"),
          ("C", "所有任务都等到最后一天统一联调验证"),
          ("D", "任务粒度越粗越好，减少沟通成本")),
      ["A"],
      "可独立交付和验证的小任务便于并行、跟踪进度与定位风险；粗粒度任务会隐藏真实进展。"),
    q("dev-req-6", "multiple", "basic", "must_know",
      "需求澄清阶段通常需要问清哪些内容？",
      opt(("A", "用户场景与主流程"),
          ("B", "边界条件与异常/失败流程"),
          ("C", "数据口径与权限范围"),
          ("D", "服务器机房的具体楼层编号")),
      ["A", "B", "C"],
      "场景、边界、异常、数据口径与权限决定了实现范围；机房位置与需求澄清无关。"),
    q("dev-req-7", "single", "intermediate", "advanced",
      "前后端联调之前，最应先约定清楚的是？",
      opt(("A", "接口契约：字段、类型、错误码与示例"),
          ("B", "前端组件的 CSS 命名规范"),
          ("C", "双方各自使用的编辑器配色方案"),
          ("D", "上线后谁负责撰写宣传文案")),
      ["A"],
      "先用契约（如 OpenAPI）对齐再并行开发，能显著减少联调期的字段扯皮与返工。"),
    q("dev-req-8", "judge", "intermediate", "advanced",
      "估算排期时只需计算编码时间，联调、测试与上线验证可忽略不计。",
      JUDGE_OPTIONS, ["B"],
      "完整交付包含自测、联调、评审、回归、发布与观察；忽略这些环节是排期失准的常见原因。"),
    q("dev-req-9", "single", "intermediate", "must_know",
      "发现需求描述存在歧义时，正确的做法是？",
      opt(("A", "及时向需求方确认并把结论补充到文档中留痕"),
          ("B", "按自己最省事的理解先实现，上线后再看反馈"),
          ("C", "暂停全部开发工作，等待下一轮迭代重新排期"),
          ("D", "把歧义写进代码注释，交由测试同学判断")),
      ["A"],
      "确认 + 留痕能避免返工，也让后续验收有依据；自行猜测往往做出与预期不符的功能。"),
    q("dev-req-10", "single", "challenge", "nice_to_know",
      "项目复盘（retrospective）最应产出什么？",
      opt(("A", "客观事实时间线、根因与有负责人的改进项"),
          ("B", "按个人贡献度排列的绩效评分表"),
          ("C", "一份不包含任何问题的项目宣传稿"),
          ("D", "把所有流程原样固化成不可修改的规范")),
      ["A"],
      "复盘对事不对人，目的是形成可跟踪的改进动作；追责或粉饰都会让问题在下次重演。"),
]

# ---- 测试与质量（6）----
QUESTIONS += [
    q("dev-test-1", "single", "basic", "must_know",
      "「测试金字塔」建议的用例分布是？",
      opt(("A", "单元测试最多，集成测试居中，端到端测试最少"),
          ("B", "端到端测试最多，单元测试只覆盖核心函数"),
          ("C", "三层用例数量完全相同，便于统一管理"),
          ("D", "只写端到端测试，单测与集成测试都可省略")),
      ["A"],
      "越底层的测试越快越稳定越便宜；E2E 覆盖关键链路即可，堆太多会拖慢且易抖动。"),
    q("dev-test-2", "single", "intermediate", "must_know",
      "单元测试最应该覆盖什么？",
      opt(("A", "纯逻辑、边界条件与异常分支的行为"),
          ("B", "第三方框架内部实现是否正确"),
          ("C", "生产数据库在高峰期的真实性能"),
          ("D", "真实用户在浏览器里的完整操作路径")),
      ["A"],
      "单测隔离外部依赖、快速反馈；框架内部与真实链路分别由上游保障和 E2E 覆盖。"),
    q("dev-test-3", "judge", "intermediate", "advanced",
      "只要代码覆盖率达到 100%，就可以认为系统没有缺陷。",
      JUDGE_OPTIONS, ["B"],
      "覆盖率只说明代码被执行过，不保证断言有效、逻辑正确或场景完整；需求理解错误更是覆盖不到的。"),
    q("dev-test-4", "single", "basic", "must_know",
      "回归测试的主要作用是？",
      opt(("A", "确认本次改动没有破坏既有功能"),
          ("B", "测量新功能在高压下的最大吞吐量"),
          ("C", "自动生成接口的对外文档与示例"),
          ("D", "统计每个模块的圈复杂度指标")),
      ["A"],
      "回归用例是改动的安全网，通常与 CI 门禁绑定；新增功能也应沉淀为后续回归的一部分。"),
    q("dev-test-5", "multiple", "intermediate", "advanced",
      "哪些检查适合放进 CI 的必跑门禁？",
      opt(("A", "静态检查与代码格式化校验"),
          ("B", "单元测试与类型检查"),
          ("C", "依赖漏洞与密钥泄露扫描"),
          ("D", "需要人工体验的主观视觉评审")),
      ["A", "B", "C"],
      "门禁应是确定、快速、可自动判定的；主观评审需人工参与，不适合做成阻断式自动门禁。"),
    q("dev-test-6", "single", "challenge", "nice_to_know",
      "面对偶发失败（flaky）的自动化用例，正确做法是？",
      opt(("A", "隔离共享状态与时间依赖，定位并消除不确定性"),
          ("B", "把失败用例标记为跳过，永久不纳入统计"),
          ("C", "在 CI 里配置为失败后自动无限重试"),
          ("D", "把所有断言改成只检查不抛异常")),
      ["A"],
      "flaky 常来自共享数据、并发时序、外部服务或随机性；靠重试或跳过只会掩盖真实缺陷。"),
]

# ---- 代码评审与规范（6）----
QUESTIONS += [
    q("dev-review-1", "single", "basic", "must_know",
      "代码评审（Code Review）最主要的价值是？",
      opt(("A", "发现缺陷与设计问题，同时共享上下文与知识"),
          ("B", "统计每位开发者的代码行数并据此排名"),
          ("C", "替代自动化测试，省去编写用例的时间"),
          ("D", "确保所有人使用完全相同的编辑器配置")),
      ["A"],
      "评审兼顾质量与团队共识，还能传播设计取舍；它不是绩效工具，也不能替代自动化测试。"),
    q("dev-review-2", "judge", "basic", "must_know",
      "提交给评审的变更越大，评审者就越容易发现其中的问题。",
      JUDGE_OPTIONS, ["B"],
      "小批量、聚焦单一目的的 PR 更容易被认真读完；超大变更容易漏审，应拆分提交。"),
    q("dev-review-3", "single", "intermediate", "advanced",
      "提出评审意见时，较合适的表达方式是？",
      opt(("A", "对事不对人，说明风险依据并给出可执行的建议"),
          ("B", "只写「这样写不好」，让作者自己领悟原因"),
          ("C", "直接替作者改完代码且不留下任何说明"),
          ("D", "把风格偏好一律标为必须修改的阻断项")),
      ["A"],
      "清晰的依据和建议能减少来回；把主观偏好与硬性缺陷区分开，也是评审效率的关键。"),
    q("dev-review-4", "single", "basic", "must_know",
      "lint / formatter 类工具主要解决什么问题？",
      opt(("A", "统一代码风格并拦截常见低级错误"),
          ("B", "验证业务需求是否被完整实现"),
          ("C", "评估系统架构的长期演进方向"),
          ("D", "替代代码评审中的设计讨论环节")),
      ["A"],
      "把风格与低级问题交给工具自动处理，评审就能聚焦逻辑、设计与风险。"),
    q("dev-review-5", "multiple", "intermediate", "advanced",
      "一条好的提交信息通常包含哪些内容？",
      opt(("A", "改动的动机与解决的问题"),
          ("B", "影响范围或需要注意的兼容风险"),
          ("C", "关联的需求/缺陷单号便于追溯"),
          ("D", "当天全部聊天记录的逐字稿")),
      ["A", "B", "C"],
      "提交信息服务于未来的自己与他人：说明「为什么」与影响面，并保留可追溯的关联。"),
    q("dev-review-6", "judge", "challenge", "nice_to_know",
      "只要配置了自动格式化工具，就不再需要对代码做人工设计评审。",
      JUDGE_OPTIONS, ["B"],
      "格式化只解决风格一致性；接口设计、边界处理、性能与安全隐患仍需要人来判断。"),
]

# ---- 发布与故障协作（6）----
QUESTIONS += [
    q("dev-release-1", "single", "basic", "must_know",
      "回滚预案应该在什么时候准备就绪？",
      opt(("A", "发布之前就写好并验证过回退路径"),
          ("B", "线上出现故障后再临时讨论方案"),
          ("C", "等复盘会议结束后统一补文档"),
          ("D", "只有在数据库变更时才需要准备")),
      ["A"],
      "回滚是发布方案的一部分，需提前确认数据兼容、开关与操作步骤，故障时才来得及止损。"),
    q("dev-release-2", "single", "intermediate", "must_know",
      "灰度（金丝雀）发布最核心的作用是？",
      opt(("A", "先用小流量验证，把异常影响面控制在可控范围"),
          ("B", "让所有用户在同一秒同时看到新版本"),
          ("C", "减少研发阶段需要编写的代码总量"),
          ("D", "自动修复新版本里存在的业务逻辑缺陷")),
      ["A"],
      "按用户/比例逐步放量并观察指标，异常时快速停止或回滚，是控制发布风险的主要手段。"),
    q("dev-release-3", "judge", "intermediate", "advanced",
      "线上故障时，应先彻底定位到根因，再着手恢复服务。",
      JUDGE_OPTIONS, ["B"],
      "优先级是「先止损、后根因」：先回滚/降级/切流恢复服务，再在不影响用户的前提下排查与分析。"),
    q("dev-release-4", "single", "intermediate", "advanced",
      "一次变更后，发布观察期最应关注哪些信号？",
      opt(("A", "错误率、延迟与关键业务指标是否异常"),
          ("B", "团队当日提交的代码行数是否达标"),
          ("C", "代码仓库的分支数量是否足够多"),
          ("D", "办公网络的下载速度是否有波动")),
      ["A"],
      "技术指标与业务指标要一起看；只盯「没报错」会漏掉转化率、订单量等静默下跌。"),
    q("dev-release-5", "multiple", "challenge", "nice_to_know",
      "一份有价值的故障复盘通常应包含哪些内容？",
      opt(("A", "按时间排列的客观事实与影响范围"),
          ("B", "根因分析与促成因素"),
          ("C", "有负责人和期限的改进项"),
          ("D", "对相关同事的个人责任认定结论")),
      ["A", "B", "C"],
      "复盘对事不对人，产出可执行的改进；追责导向会让信息被隐藏，反而阻碍根因定位。"),
    q("dev-release-6", "single", "challenge", "nice_to_know",
      "特性开关（feature flag）在工程上的主要价值是？",
      opt(("A", "解耦「部署」与「发布」，出问题时可快速关闭"),
          ("B", "让代码无需经过测试就能安全上线"),
          ("C", "自动合并所有长期存在的特性分支"),
          ("D", "替代版本控制系统的分支管理功能")),
      ["A"],
      "代码可以先部署但保持关闭，按需灰度放量；一旦异常直接关开关，无需再次构建回滚。"),
]


def _length_ratio(item: dict) -> float:
    if item["kind"] == "judge":
        return 1.0
    ans = set(item["answer"])
    right = [len(o["text"]) for o in item["options"] if o["key"] in ans]
    wrong = [len(o["text"]) for o in item["options"] if o["key"] not in ans]
    if not right or not wrong:
        return 1.0
    return (sum(right) / len(right)) / max(1, sum(wrong) / len(wrong))


def to_staging(questions: list[dict]) -> list[dict]:
    """canonical → staging 素材格式（额外带 id 供 export 分类；question_merge 会忽略 id）。"""
    records = []
    for index, item in enumerate(questions, start=1):
        kind = item["kind"]
        if kind == "judge":
            answer = "正确" if item["answer"] == ["A"] else "错误"
            options = JUDGE_OPTIONS
        elif kind == "single":
            answer = item["answer"][0]
            options = item["options"]
        else:  # multiple
            answer = ",".join(item["answer"])
            options = item["options"]
        records.append({
            "n": index,
            "id": item["id"],
            "language": item["language"],
            "direction": item["direction"],
            "kind": kind,
            "difficulty": item["difficulty"],
            "essentiality": item["essentiality"],
            "stem": item["prompt"],
            "options": options,
            "answer": answer,
            "explanation": item["explanation"],
        })
    return records


def validate(questions: list[dict]) -> None:
    seen_ids, seen_stems = set(), set()
    for item in questions:
        assert item["id"] not in seen_ids, f"重复 id: {item['id']}"
        seen_ids.add(item["id"])
        assert item["prompt"] not in seen_stems, f"重复题干: {item['prompt']}"
        seen_stems.add(item["prompt"])
        opts, ans = item["options"], item["answer"]
        assert item["kind"] in ("single", "multiple", "judge")
        if item["kind"] == "judge":
            assert opts == JUDGE_OPTIONS, f"{item['id']} 判断题选项文案不符"
            assert ans in (["A"], ["B"]), f"{item['id']} 判断题答案应为 A 或 B"
        else:
            keys = {o["key"] for o in opts}
            assert 2 <= len(opts) <= 6, f"{item['id']} 选项数越界"
            assert set(ans) <= keys, f"{item['id']} answer 越出 options"
            if item["kind"] == "single":
                assert len(ans) == 1, f"{item['id']} 单选答案应恰 1"
            else:
                assert len(ans) >= 2, f"{item['id']} 多选答案应 ≥2"
        assert item["explanation"].strip(), f"{item['id']} explanation 为空"
        assert item["difficulty"] in ("basic", "intermediate", "challenge")
        assert item["essentiality"] in ("must_know", "advanced", "nice_to_know")
        assert item["language"] == "", f"{item['id']} 研发实践题语言必须为空串"
        assert item["direction"] == "研发工程实践"
        ratio = _length_ratio(item)
        assert ratio <= 2.9, f"{item['id']} 正确项/干扰项长度比 {ratio:.2f} > 2.9"
    # 分类配额、分层覆盖与判断题极性
    cats = Counter(item["id"].split("-")[1] for item in questions)
    assert cats == {"git": 12, "cicd": 10, "req": 10, "test": 6,
                    "review": 6, "release": 6}, f"分类配额不符: {dict(cats)}"
    assert len(questions) == 50, f"题量应为 50，实际 {len(questions)}"
    tiers = {item["essentiality"] for item in questions}
    assert tiers == {"must_know", "advanced", "nice_to_know"}, f"三档不齐: {tiers}"
    judges = [item for item in questions if item["kind"] == "judge"]
    polarity = Counter(item["answer"][0] for item in judges)
    assert len(judges) == 11 and polarity == {"A": 1, "B": 10}, (
        f"判断题极性配置不符（须 1 正确 / 10 错误，保住通用桶 0.4–0.6）: {dict(polarity)}"
    )


def main() -> None:
    validate(QUESTIONS)
    records = to_staging(QUESTIONS)
    STAGING_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写出 staging 素材：{STAGING_PATH}")
    print(f"题目数：{len(records)}（下一步请运行 "
          f"`python -m app.services.question_merge --write` 重建 questions.json）")


if __name__ == "__main__":
    main()
