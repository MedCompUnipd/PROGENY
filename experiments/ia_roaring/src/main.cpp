// Experimental IA count engine. Scientific policy is supplied by PROGENY Python.
#include <roaring/roaring.h>
#include <omp.h>
#include <sys/resource.h>
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
using namespace roaring::api;
using Bitmap = std::unique_ptr<roaring_bitmap_t, decltype(&roaring_bitmap_free)>;
Bitmap bitmap() {
    auto* p = roaring_bitmap_create();
    if (!p) throw std::bad_alloc();
    return Bitmap(p, roaring_bitmap_free);
}
std::vector<std::string> split(const std::string& s, char delimiter='\t') {
    std::vector<std::string> result;
    std::size_t start=0;
    for (;;) {
        auto end=s.find(delimiter,start);
        result.push_back(s.substr(start,end==std::string::npos?end:end-start));
        if (end==std::string::npos) return result;
        start=end+1;
    }
}
std::string quote(const std::string& s) {
    std::string result="\"";
    constexpr char hex[]="0123456789abcdef";
    for (unsigned char c:s) {
        if (c=='"'||c=='\\') {result+='\\'; result+=static_cast<char>(c);}
        else if (c<32) {result+="\\u00"; result+=hex[c>>4]; result+=hex[c&15];}
        else result+=static_cast<char>(c);
    }
    return result+'"';
}
using Counts=std::map<std::string,std::uint64_t>;
void json_map(std::ostream& out,const Counts& counts) {
    out<<"{"; bool first=true;
    for(const auto& [key,n]:counts) {if(!first)out<<",";first=false;out<<quote(key)<<":"<<n;}
    out<<"}";
}
struct Node {
    std::string id,aspect;
    bool root;
    std::vector<std::size_t> parents;
    Bitmap members=bitmap();
};
struct Policy {std::string canonical,status,source_aspect;};
bool has_not(std::string_view s) {
    for(;;) {auto pos=s.find('|');if(s.substr(0,pos)=="NOT")return true;if(pos==std::string_view::npos)return false;s.remove_prefix(pos+1);}
}
std::uint64_t number(const std::string& s) {
    std::uint64_t value=0;
    auto [end,ec]=std::from_chars(s.data(),s.data()+s.size(),value);
    if(ec!=std::errc()||end!=s.data()+s.size())throw std::runtime_error("invalid integer");
    return value;
}
int run(int argc,char** argv) {
    if(argc!=7)throw std::runtime_error("usage: engine GRAPH POLICY COUNTS AUDIT THREADS MAX_ADDRESS_BYTES (GAF on stdin)");
    if(std::filesystem::exists(argv[3])||std::filesystem::exists(argv[4]))throw std::runtime_error("output already exists");
    auto threads=number(argv[5]);auto memory=number(argv[6]);
    if(threads<1||threads>64||memory<64*1024*1024ULL)throw std::runtime_error("invalid resource limit");
    rlimit old{};if(getrlimit(RLIMIT_AS,&old))throw std::runtime_error("getrlimit failed");
    rlimit limit{static_cast<rlim_t>(memory),old.rlim_max};
    if(old.rlim_cur!=RLIM_INFINITY)limit.rlim_cur=std::min(limit.rlim_cur,old.rlim_cur);
    if(setrlimit(RLIMIT_AS,&limit))throw std::runtime_error("setrlimit failed");
    rlimit core{0,0};if(setrlimit(RLIMIT_CORE,&core))throw std::runtime_error("cannot disable core dumps");
    omp_set_num_threads(static_cast<int>(threads));
    std::vector<Node> nodes;
    std::unordered_map<std::string,std::size_t> index;
    std::vector<std::string> parent_strings;
    std::ifstream graph(argv[1]);std::string line;
    if(!graph||!std::getline(graph,line)||line!="go_id\taspect\tis_root\tparents")throw std::runtime_error("invalid graph header");
    while(std::getline(graph,line)) {
        auto f=split(line);
        if(f.size()!=4||(f[1]!="F"&&f[1]!="P"&&f[1]!="C")||(f[2]!="0"&&f[2]!="1"))throw std::runtime_error("invalid graph row");
        if(!index.emplace(f[0],nodes.size()).second)throw std::runtime_error("duplicate node");
        nodes.push_back(Node{f[0],f[1],f[2]=="1",{},bitmap()});parent_strings.push_back(f[3]);
    }
    if(nodes.empty())throw std::runtime_error("empty graph");
    std::vector<std::size_t> children(nodes.size());
    for(std::size_t i=0;i<nodes.size();++i)if(!parent_strings[i].empty()) {
        for(const auto& p:split(parent_strings[i],',')) {
            auto j=index.at(p);
            if(nodes[i].aspect!=nodes[j].aspect)throw std::runtime_error("cross aspect graph edge");
            nodes[i].parents.push_back(j);++children[j];
        }
        auto ps=nodes[i].parents;std::sort(ps.begin(),ps.end());
        if(std::adjacent_find(ps.begin(),ps.end())!=ps.end())throw std::runtime_error("duplicate parent");
    }
    auto pending=children;std::queue<std::size_t> ready;std::vector<std::size_t> order;
    for(std::size_t i=0;i<nodes.size();++i)if(!pending[i])ready.push(i);
    while(!ready.empty()) {auto i=ready.front();ready.pop();order.push_back(i);for(auto p:nodes[i].parents)if(!--pending[p])ready.push(p);}
    if(order.size()!=nodes.size())throw std::runtime_error("cyclic graph");
    std::unordered_map<std::string,Policy> policy;
    std::ifstream policy_file(argv[2]);
    if(!policy_file||!std::getline(policy_file,line)||line!="go_id\tcanonical\tstatus\tsource_aspect")throw std::runtime_error("invalid policy header");
    while(std::getline(policy_file,line)) {
        auto f=split(line);if(f.size()!=4)throw std::runtime_error("invalid policy row");
        if(!policy.emplace(f[0],Policy{f[1],f[2],f[3]}).second)throw std::runtime_error("duplicate policy id");
    }
    Counts counts,evidence,resolutions,cross,source_bad,invalid;
    std::unordered_map<std::string,std::uint32_t> proteins;
    std::string minimum="99999999",maximum="00000000";
    std::string last_protein;std::uint32_t last_id=0;bool have_last=false;
    std::uint64_t line_number=0;auto started=std::chrono::steady_clock::now();
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    while(std::getline(std::cin,line)) {
        ++line_number;
        while(!line.empty()&&(line.back()=='\r'||line.back()=='\n'))line.pop_back();
        if(line.empty()||line[0]=='!')continue;
        if(line.find_first_not_of(" \t\r\n\v\f")==std::string::npos)continue;
        ++counts["data_rows"];
        if(counts["data_rows"]%5000000==0)std::cerr<<"GAF_ROWS="<<counts["data_rows"]<<" PROTEINS="<<proteins.size()<<'\n';
        for(unsigned char c:line)if(c>127)throw std::runtime_error("non-ASCII GAF line "+std::to_string(line_number));
        std::array<std::string_view,17> f{};std::size_t start=0,n=0;
        for(;;) {
            if(n==17)throw std::runtime_error("GAF has more than 17 fields");
            auto end=line.find('\t',start);
            f[n++]=std::string_view(line).substr(start,end==std::string::npos?end:end-start);
            if(end==std::string::npos)break;start=end+1;
        }
        if(n!=17)throw std::runtime_error("GAF does not have 17 fields");
        if(f[0]!="UniProtKB") {++counts["non_uniprot_rows_excluded"];continue;}
        if(f[1].empty()||!f[4].starts_with("GO:"))throw std::runtime_error("invalid GAF identity/GO");
        if(f[13].size()!=8||!std::all_of(f[13].begin(),f[13].end(),[](char c){return c>='0'&&c<='9';}))throw std::runtime_error("invalid annotation date");
        minimum=std::min(minimum,std::string(f[13]));maximum=std::max(maximum,std::string(f[13]));
        if(has_not(f[3])) {++counts["not_rows_excluded"];continue;}
        ++counts["positive_rows"];++evidence[std::string(f[6])];
        auto it=policy.find(std::string(f[4]));
        Policy unknown{"","unknown",""};const auto& p=it==policy.end()?unknown:it->second;
        ++resolutions[p.status];
        if(p.canonical.empty()) {++counts["unresolved_go_rows_excluded"];continue;}
        std::string source=p.source_aspect.empty()?"?":p.source_aspect;
        if(f[8]!="F"&&f[8]!="P"&&f[8]!="C") {++invalid[std::string(f[4])+"|GAF="+std::string(f[8])+"|source="+source];continue;}
        if(f[8]!=p.source_aspect) {++source_bad[std::string(f[4])+"|GAF="+std::string(f[8])+"|source="+source];continue;}
        auto canonical=index.find(p.canonical);
        if(canonical==index.end()) {++counts["inactive_or_unprojected_go_rows_excluded"];continue;}
        auto node=canonical->second;
        if(p.status=="replaced"&&p.source_aspect!=nodes[node].aspect) {++cross[std::string(f[4])+"|"+p.source_aspect+"->"+p.canonical+"|"+nodes[node].aspect];continue;}
        if(f[4]!=p.canonical)++counts["remapped_go_rows"];
        std::uint32_t id;
        if(have_last&&f[1]==last_protein)id=last_id;
        else {
            auto found=proteins.find(std::string(f[1]));
            if(found==proteins.end()) {
                if(proteins.size()>=std::numeric_limits<std::uint32_t>::max())throw std::runtime_error("protein ID capacity exceeded");
                id=static_cast<std::uint32_t>(proteins.size());proteins.emplace(std::string(f[1]),id);
            }else id=found->second;
            last_protein=f[1];last_id=id;have_last=true;
        }
        roaring_bitmap_add(nodes[node].members.get(),id);
    }
    if(!std::cin.eof())throw std::runtime_error("GAF input read failure");
    counts["unique_direct_proteins"]=proteins.size();counts["unique_direct_pairs"]=0;
    for(auto& node:nodes) {counts["unique_direct_pairs"]+=roaring_bitmap_get_cardinality(node.members.get());roaring_bitmap_run_optimize(node.members.get());}
    decltype(proteins)().swap(proteins);
    std::cerr<<"GAF_SCAN_SECONDS="<<std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()<<'\n';
    std::size_t processed=0;
    for(auto i:order) {
        for(auto parent:nodes[i].parents)roaring_bitmap_or_inplace(nodes[parent].members.get(),nodes[i].members.get());
        roaring_bitmap_run_optimize(nodes[i].members.get());
        if(++processed%1000==0)std::cerr<<"PROPAGATED_GO_NODES="<<processed<<" TOTAL_GO_NODES="<<nodes.size()<<'\n';
    }
    std::map<std::string,Bitmap> aspect_members;
    for(const auto& node:nodes) {
        if(!aspect_members.contains(node.aspect))aspect_members.emplace(node.aspect,bitmap());
        roaring_bitmap_or_inplace(aspect_members.at(node.aspect).get(),node.members.get());
    }
    Counts aspect_counts;
    for(const auto& [aspect,b]:aspect_members)if(roaring_bitmap_get_cardinality(b.get()))aspect_counts[aspect]=roaring_bitmap_get_cardinality(b.get());
    std::vector<std::uint64_t> term_counts(nodes.size()),parent_counts(nodes.size());
    for(std::size_t i=0;i<nodes.size();++i)term_counts[i]=roaring_bitmap_get_cardinality(nodes[i].members.get());
    // No shared mutable bitmap is touched in this parallel phase.
    #pragma omp parallel for schedule(dynamic,16)
    for(std::size_t i=0;i<nodes.size();++i) {
        auto parents=nodes[i].parents;
        std::sort(parents.begin(),parents.end(),[&](auto a,auto b){return term_counts[a]<term_counts[b];});
        if(nodes[i].root||parents.empty()) {
            auto found=aspect_counts.find(nodes[i].aspect);parent_counts[i]=found==aspect_counts.end()?0:found->second;
        } else if(parents.size()==1)parent_counts[i]=term_counts[parents[0]];
        else if(parents.size()==2)parent_counts[i]=roaring_bitmap_and_cardinality(nodes[parents[0]].members.get(),nodes[parents[1]].members.get());
        else {
            Bitmap intersection(roaring_bitmap_copy(nodes[parents[0]].members.get()),roaring_bitmap_free);
            if(!intersection)std::abort();
            for(std::size_t j=1;j<parents.size();++j)roaring_bitmap_and_inplace(intersection.get(),nodes[parents[j]].members.get());
            parent_counts[i]=roaring_bitmap_get_cardinality(intersection.get());
        }
    }
    std::ofstream out(argv[3]);if(!out)throw std::runtime_error("cannot create counts output");
    out<<"go_id\taspect\tterm_count\tparent_conjunction_count\n";
    for(std::size_t i=0;i<nodes.size();++i) {
        if(term_counts[i]>parent_counts[i])throw std::runtime_error("inconsistent counts");
        out<<nodes[i].id<<'\t'<<nodes[i].aspect<<'\t'<<term_counts[i]<<'\t'<<parent_counts[i]<<'\n';
    }
    out.close();if(!out)throw std::runtime_error("counts write failure");
    std::ofstream audit(argv[4]);if(!audit)throw std::runtime_error("cannot create audit output");
    audit<<"{";for(const auto& [k,v]:counts)audit<<quote(k)<<":"<<v<<",";
    audit<<"\"minimum_annotation_date\":"<<quote(minimum=="99999999"?"":minimum)<<",";
    audit<<"\"maximum_annotation_date\":"<<quote(maximum=="00000000"?"":maximum)<<",";
    audit<<"\"evidence_code_counts\":";json_map(audit,evidence);
    audit<<",\"go_resolution_status_counts\":";json_map(audit,resolutions);
    audit<<",\"aspect_protein_counts\":";json_map(audit,aspect_counts);
    for(const auto& [prefix,m]:std::vector<std::pair<std::string,Counts>>{{"cross_aspect_replacement",cross},{"source_aspect_mismatch",source_bad},{"invalid_gaf_aspect",invalid}}) {
        std::uint64_t sum=0;for(const auto& [k,v]:m)sum+=v;
        audit<<","<<quote(prefix+"_rows_excluded")<<":"<<sum<<","<<quote(prefix+"_mapping_counts")<<":";json_map(audit,m);
    }
    rusage usage{};if(getrusage(RUSAGE_SELF,&usage))throw std::runtime_error("getrusage failed");
    audit<<",\"native_peak_rss_kib\":"<<usage.ru_maxrss;
    audit<<",\"native_effective_address_space_bytes\":"<<limit.rlim_cur;
    audit<<"}\n";audit.close();if(!audit)throw std::runtime_error("audit write failure");
    std::cerr<<"IA_NATIVE_COUNTS=PASS TERMS="<<nodes.size()<<'\n';return 0;
}
int main(int argc,char** argv) {
    try{return run(argc,argv);}catch(const std::exception& e){std::cerr<<"IA_NATIVE_ERROR="<<e.what()<<'\n';return 1;}
}
