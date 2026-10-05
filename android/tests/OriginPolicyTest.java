package in.cosmosgroups.portal;
public class OriginPolicyTest {
 public static void main(String[] args) {
  String[] accepted={OriginPolicy.HOME,"https://cosmos-ecosystem-staging.onrender.com/api/export?month=2026-10","https://cosmos-ecosystem-staging.onrender.com:443"};
  String[] rejected={"http://cosmos-ecosystem-staging.onrender.com/","https://cosmos-ecosystem-staging.onrender.com.evil.example/","https://cosmos-ecosystem-staging.onrender.com@evil.example/","https://evil@cosmos-ecosystem-staging.onrender.com/","https://cosmos-ecosystem-staging.onrender.com:444/","file:///etc/passwd","javascript:alert(1)","intent://example/","not a URL",null};
  for(String url:accepted)if(!OriginPolicy.trusted(url))throw new AssertionError(url);
  for(String url:rejected)if(OriginPolicy.trusted(url))throw new AssertionError(url);
  System.out.println("Origin policy: 13 cases passed");
 }
}
