# 素材许可声明 · fe-interview（MIT）

本文件是 `backend/app/seed/questions.json` 中 `source = "fe-interview"` 的 20 道题的**许可凭证**。
`backend/tests/test_r12_question_merge.py::test_license_notice_present_when_third_party_source_in_seed`
会把「seed 里出现该来源 ⇒ 本文件存在且含 https 上游链接」钉成机器门槛：删了本文件或写成空口径，
测试直接红。

## 1 上游与素材

- 上游仓库：<https://github.com/haizlin/fe-interview>
- 上游许可证原文：<https://github.com/haizlin/fe-interview/blob/master/LICENSE>
- 许可证类型：MIT（GitHub 许可证接口返回 `"spdx_id": "MIT"`，`LICENSE` 文件 1066 字节，
  blob sha `808b3e191fdcaa5551adf21ef50e907a52b9de7c`，2026-11-02 核对）
- 版权人（照抄上游 LICENSE 首行）：`Copyright (c) 2019 haizhilin`
- 本方使用的素材文件：`docs/question-bank-staging/04-fe-interview20.json`（20 道，均来自上游
  「前端面试每日 3+1」的题干主题：HTML / CSS / JavaScript）

## 2 改写说明（AI 改写版，非原样转载）

本批 20 道题是**基于上游题目的 AI 改写版**，不是上游文本的原样复制：

1. 上游题目以**开放式问答**为主（如「请描述一下 cookies、sessionStorage 和 localStorage 的区别？」），
   本题库只收客观题，因此由 AI 改写成**四选一单选题**——保留原题的考点与正确答案含义，
   自拟三个干扰项（均为常见误解，而非随意堆砌）。
2. 题干、选项、解析均由 AI 重新组织表述；素材文件里的 `source_title` 字段保留了对应的上游原题
   标题，便于逐条回溯（`source_title` 不进种子，只作 staging 里的溯源信息）。
3. 解析为 AI 撰写的判分依据，不是上游原文。
4. 改写后仍可能残留上游的表达方式与知识点组织方式，因此**按上游 MIT 许可使用**，不主张独立版权；
   本仓库对该批数据的改动（改写、结构化）同样以 MIT 发布。

## 3 MIT 许可证全文（逐字照抄上游 LICENSE）

```text
MIT License

Copyright (c) 2019 haizhilin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 4 其余三个来源

`tiji` / `local100` / `iq380` 三份素材（共 499 道）为团队自建或本地生成，不含第三方受限内容，
故只标 `source`、不附 NOTICE。引入新素材前先确认许可证：GPL / 无 LICENSE 的仓库一律不引入
（团队记忆：题库只用自建或 MIT 源）。
